"""저장 기반 도구들: 역순 줄 생성기, JSONL append/원자적 재작성, 채번 파일.

역순 생성기(`iter_lines_reversed`)가 이 앱의 메모리 절약 핵심이다.
list/search는 파일을 처음부터 읽지 않고 끝에서 블록 단위로 거꾸로 읽어
`최근 추가분`부터 유한 메모리로 뽑아낸다. 상세 전략은 README 참조.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path

from budget_app.errors import StorageError, ValidationError

#: 기본 읽기 블록(8KiB). 역순 생성기의 메모리 상한이 된다.
DEFAULT_BLOCK_SIZE: int = 8192


def iter_lines_reversed(path: Path, block_size: int = DEFAULT_BLOCK_SIZE) -> Iterator[str]:
    """파일 끝에서부터 줄을 거꾸로 yield한다(빈 줄 제외, UTF-8 디코딩).

    블록 단위로 뒤에서 읽기 때문에 전체를 메모리에 올리지 않는다.
    UTF-8 후속 바트는 0x0A와 겹치지 않으므로 바이트 경계에서 '\n'으로
    자르는 디코딩은 안전하다. 파일이 없으면 아무것도 yield하지 않는다.
    """
    try:
        size = path.stat().st_size
    except FileNotFoundError:
        return
    with path.open("rb") as handle:
        position = size
        pending = b""
        while position > 0:
            read_size = min(block_size, position)
            position -= read_size
            handle.seek(position)
            chunk = handle.read(read_size)
            segments = (chunk + pending).split(b"\n")
            # 역순 읽기에서는 첫 조각만 왼쪽(미읽기 영역)과 이어질 수 있다.
            # 나머지 조각은 우측 끝(\n 또는 이전 블록 경계)이 확정된 완전한 줄.
            pending = segments[0]
            for segment in reversed(segments[1:]):
                if segment.strip():
                    yield _decode(segment, path)
        if pending.strip():
            yield _decode(pending, path)


def _decode(raw: bytes, path: Path) -> str:
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StorageError(
            f"{path.name}에 UTF-8로 읽을 수 없는 줄이 있습니다.",
            "해당 파일을 UTF-8로 다시 저장하거나 손상 줄을 삭제하세요.",
        ) from exc


class JsonlStore:
    """한 개의 JSONL 파일을 다루는 최소 저장소.

    - append/append_many: 한 줄(들)을 끝에 추가. 마지막 한 번의 write+fsync.
    - iter_dicts / iter_dicts_reversed: 순방향/역순 지연(lazy) 읽기.
    - replace_stream: 전체 재작성을 임시 파일 + os.replace로 원자적으로.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def append(self, record: Mapping[str, object]) -> None:
        self.append_many([record])

    def append_many(self, records: Iterable[Mapping[str, object]]) -> int:
        """여러 레코드를 '한 번의' 추가 쓰기로 저장한다(단건 추가의 빠른 경로)."""
        lines = "".join(
            json.dumps(record, ensure_ascii=False) + "\n" for record in records
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        count = lines.count("\n")
        if count == 0:
            return 0
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(lines)
            handle.flush()
            os.fsync(handle.fileno())
        return count

    def iter_dicts(self) -> Iterator[dict[str, object]]:
        if not self.path.exists():
            return
        with self.path.open("r", encoding="utf-8", newline="\n") as handle:
            for number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                yield self._parse(line, f"{number}번째 줄")

    def iter_dicts_reversed(self) -> Iterator[dict[str, object]]:
        for number, line in enumerate(iter_lines_reversed(self.path), start=1):
            yield self._parse(line + "\n", f"끝에서 {number}번째 줄")

    def _parse(self, line: str, where: str) -> dict[str, object]:
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                f"{self.path.name} {where}이(가) JSON이 아닙니다.",
                "손상된 줄을 삭제하거나 백업에서 복구하세요.",
            ) from exc
        if not isinstance(record, dict):
            raise ValidationError(
                f"{self.path.name} {where}이(가) 객체가 아닙니다.",
                "한 줄에 JSON 객체 하나 형식으로 저장됩니다.",
            )
        return record

    def replace_stream(self, records: Iterable[Mapping[str, object]]) -> None:
        """기록 흐름을 받아 임시 파일에 쓴 뒤 os.replace로 원자적 교체.

        중간에 실패하면 임시 파일만 지우고 원본은 건드리지 않는다(롤백).
        records는 제네레이터라도 되며 전부 메모리에 담지 않는다.
        """
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.parent / f"{self.path.name}.{os.getpid()}.tmp"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                for record in records:
                    handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise


class SequenceFile:
    """거래 id 채번 카운터(meta.json 단일 객체).

    append-only 추가와 update/delete 재작성을 오가도 id가 중복되지 않게,
    다음 번호를 파일에 따로 저장한다. 사용 순서는 'peek로 id 형식 →
    advance로 확정 → 거래 append'. 거래 쓰기가 실패해도 번호는 이미
    쓰였으므로 재사용되지 않고, 그 결과 id는 항상 단조 증가한다.

    meta.json이 없거나 비었는데 거래 파일에 id가 남아 있는 회복 상황을
    대비해 `fallback`(예: 기존 최대 id + 1)을 선택적으로 받는다. 폴백이
    없으면 예전처럼 1부터 시작한다.
    """

    def __init__(self, path: Path, fallback: Callable[[], int | None] | None = None) -> None:
        self.path = path
        self._fallback = fallback

    def peek(self) -> int:
        try:
            raw = self.path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return self._fresh_start()
        stripped = raw.strip()
        if not stripped:
            return self._fresh_start()
        try:
            data = json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValidationError(
                "meta.json이 손상됐습니다.",
                "json을 수리할 수 없으면 meta.json을 삭제하세요. 삭제 후에는 "
                "기존 거래의 최대 id + 1(거래가 없으면 1)부터 채번을 이어갑니다.",
            ) from exc
        if not isinstance(data, dict) or not isinstance(data.get("next_seq"), int):
            raise ValidationError(
                "meta.json 형식이 잘못됐습니다.",
                "json을 수리할 수 없으면 meta.json을 삭제하세요. 삭제 후에는 "
                "기존 거래의 최대 id + 1(거래가 없으면 1)부터 채번을 이어갑니다.",
            )
        return int(data["next_seq"])

    def _fresh_start(self) -> int:
        """meta.json이 없을 때의 시작 번호: 회복 폴백 우선, 없으면 1."""
        if self._fallback is not None:
            recovered = self._fallback()
            if recovered is not None:
                return recovered
        return 1

    def advance(self) -> int:
        """번호를 하나 쓰고 확정(원자적 교체)한다. 사용 전 값을 돌려준다."""
        current = self.peek()
        self._write(current + 1)
        return current

    def advance_by(self, count: int) -> int:
        """count개를 한 번에 쓰고 사용 시작 번호를 돌려준다(import용)."""
        current = self.peek()
        self._write(current + max(count, 0))
        return current

    def _write(self, next_seq: int) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.parent / f"{self.path.name}.{os.getpid()}.tmp"
        try:
            with temp.open("w", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps({"next_seq": next_seq}) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, self.path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise


__all__ = ["DEFAULT_BLOCK_SIZE", "JsonlStore", "SequenceFile", "iter_lines_reversed"]
