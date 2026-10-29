"""JSONL 읽기·쓰기, 역순 generator, 거래 ID 관리.

iter_lines_reversed는 파일 끝부터 읽는 generator다.
거래일 정렬은 repositories의 외부 정렬을 사용한다.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterable, Iterator, Mapping
from pathlib import Path

from budget_app.errors import StorageError, ValidationError

#: 기본 읽기 블록 크기. 메모리 사용량은 처리 중인 줄 길이에도 영향을 받는다.
DEFAULT_BLOCK_SIZE: int = 8192


def iter_lines_reversed(path: Path, block_size: int = DEFAULT_BLOCK_SIZE) -> Iterator[str]:
    """파일 끝에서부터 줄을 거꾸로 yield한다(빈 줄 제외, UTF-8 디코딩).

    블록 단위로 뒤에서 읽기 때문에 전체를 메모리에 올리지 않는다.
    UTF-8 멀티바이트 문자에는 줄바꿈 바이트(0x0A)가 포함되지 않는다.
    따라서 바이트 단위로 줄을 나눈 뒤 decode할 수 있다. 파일이 없으면 종료한다.
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
    """JSONL 파일 하나의 읽기·쓰기를 담당한다.

    - append/append_many: record를 파일 끝에 쓰고 fsync한다.
    - iter_dicts / iter_dicts_reversed: 정방향/역순으로 필요한 줄만 읽는다.
    - replace_stream: 임시 파일을 모두 쓴 뒤 os.replace로 교체한다.
    """

    def __init__(self, path: Path) -> None:
        self.path = path

    def exists(self) -> bool:
        return self.path.exists() and self.path.stat().st_size > 0

    def append(self, record: Mapping[str, object]) -> None:
        self.append_many([record])

    def append_many(self, records: Iterable[Mapping[str, object]]) -> int:
        """여러 record를 문자열로 모아 파일 끝에 한 번에 쓴다."""
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
        """record를 차례로 임시 파일에 쓴 뒤 os.replace로 교체한다.

        실패하면 임시 파일만 지우고 원본을 보존한다.
        records는 generator도 받을 수 있으며 전체를 메모리에 모으지 않는다.
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
    """meta.json에 다음 거래 번호를 저장한다.

    peek는 양의 정수인지, 기존 거래 번호와 겹치지 않는지 검사한다.
    advance는 거래를 쓰기 전에 번호를 예약한다. 거래 저장에 실패해도
    예약한 번호는 되돌리지 않는다. 여러 프로세스의 동시 쓰기는 지원하지 않는다.

    fallback은 기존 최대 ID + 1을 반환한다. 파일이 없으면 이 값부터
    시작하고, 파일이 있으면 다음 번호의 하한으로 쓴다. 삭제된 거래의
    과거 ID는 meta.json 없이 복구할 수 없다.
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
                "백업에서 복구하거나 meta.json을 삭제하세요. 삭제 후에는 "
                "남은 거래의 최대 ID + 1(거래가 없으면 1)부터 이어집니다.",
            ) from exc
        current = data.get("next_seq") if isinstance(data, dict) else None
        if type(current) is not int or current < 1:
            raise ValidationError(
                "meta.json의 next_seq는 1 이상의 정수여야 합니다.",
                "백업에서 복구하거나 meta.json을 삭제하세요. 삭제 후에는 "
                "남은 거래의 최대 ID + 1(거래가 없으면 1)부터 이어집니다.",
            )
        minimum = self._fresh_start()
        if current < minimum:
            raise ValidationError(
                f"meta.json의 다음 거래 번호({current})가 기존 거래 번호와 겹칩니다.",
                "meta.json을 백업에서 복구하거나 삭제한 뒤 다시 실행하세요. "
                "삭제 후에는 기존 거래의 최대 id + 1부터 이어집니다.",
            )
        return current

    def _fresh_start(self) -> int:
        """fallback으로 다음 거래 번호의 하한을 구한다. 없으면 1을 쓴다."""
        if self._fallback is not None:
            recovered = self._fallback()
            if recovered is not None:
                return recovered
        return 1

    def advance(self) -> int:
        """번호 하나를 예약하고 예약한 번호를 반환한다."""
        current = self.peek()
        self._write(current + 1)
        return current

    def advance_by(self, count: int) -> int:
        """import에 사용할 번호 count개를 예약하고 첫 번호를 반환한다."""
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
