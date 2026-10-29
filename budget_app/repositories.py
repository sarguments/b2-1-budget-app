"""거래·카테고리·예산 repository와 거래 ID 발급.

- TransactionRepository: 거래 추가/조회/수정/삭제. 단건 추가만 append,
  import·수정·삭제는 임시 파일을 쓴 뒤 os.replace로 교체한다.
- CategoryRepository: 카테고리 추가/목록/삭제, 첫 실행 기본값 자동 생성.
- BudgetRepository: 월 예산 upsert(한 달 한 개)과 목록.

각 repository는 파일 경로와 저장 방식을 관리하고, 값 검증은 model에 맡긴다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from contextlib import ExitStack, closing
import heapq
import json
from itertools import chain
from pathlib import Path
import tempfile

from budget_app.errors import ConflictError, NotFoundError, ValidationError
from budget_app.models import Budget, Category, NewTransaction, Transaction
from budget_app.parsing import format_transaction_id, is_transaction_id
from budget_app.storage import JsonlStore, SequenceFile

#: 카테고리 파일이 없거나 비었을 때 등록할 기본값.
DEFAULT_CATEGORY_NAMES: tuple[str, ...] = ("parts", "tools", "edu", "transit", "food", "etc")

#: 외부 정렬의 메모리와 동시 파일 수를 제한한다.
SORT_CHUNK_SIZE = 1024
MERGE_WIDTH = 32


def _transaction_order(tx: Transaction) -> tuple[str, int]:
    return tx.date, int(tx.id[3:])


def _merge_runs(paths: list[Path]) -> Iterator[Transaction]:
    """정렬된 JSONL 파일을 일정한 수만 열어 merge한다."""
    with ExitStack() as stack:
        def read(path: Path) -> Iterator[Transaction]:
            handle = stack.enter_context(path.open("r", encoding="utf-8"))
            for line in handle:
                yield Transaction.from_json_dict(json.loads(line))

        yield from heapq.merge(
            *(read(path) for path in paths), key=_transaction_order, reverse=True
        )


def _write_run(path: Path, transactions: Iterable[Transaction]) -> None:
    """정렬 작업용 파일을 쓴다. 사용자 데이터 파일은 변경하지 않는다."""
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for tx in transactions:
            handle.write(json.dumps(tx.to_json_dict(), ensure_ascii=False) + "\n")


class TransactionRepository:
    """transactions.jsonl 한 파일의 읽기·쓰기와 ID 발급을 담당한다."""

    def __init__(self, data_dir: Path) -> None:
        self._store = JsonlStore(data_dir / "transactions.jsonl")
        # 기존 거래의 최대 ID로 복구하거나 meta.json의 다음 번호를 검증한다.
        self._seq = SequenceFile(data_dir / "meta.json", fallback=self._recover_from_ids)

    def _recover_from_ids(self) -> int | None:
        """거래 파일의 유효한 `TX-` id 중 최대값 + 1. 거래가 없으면 None.

        거래 파일을 순회하며 다음 번호의 하한을 계산한다.
        잘못된 ID가 있으면 추가를 중단한다. 다른 필드는 거래를 읽을 때 검증한다.
        """
        best: int | None = None
        for record in self._store.iter_dicts():
            tx_id = record.get("id")
            if not isinstance(tx_id, str) or not is_transaction_id(tx_id):
                raise ValidationError(
                    "transactions.jsonl에 잘못된 거래 ID가 있습니다.",
                    "거래 파일을 백업에서 복구하거나 잘못된 ID를 확인하세요.",
                )
            seq = int(tx_id[len("TX-"):])
            if best is None or seq >= best:
                best = seq + 1
        return best

    def add(self, draft: NewTransaction) -> Transaction:
        """ID를 발급해 거래 한 건을 저장하고 Transaction을 반환한다."""
        tx = Transaction.from_draft(format_transaction_id(self._seq.peek()), draft)
        self._seq.advance()
        self._store.append(tx.to_json_dict())
        return tx

    def add_many(self, drafts: Iterable[NewTransaction]) -> list[Transaction]:
        """초안을 검증하고 기존 거래와 합쳐 임시 파일에 쓴 뒤 교체한다.

        append가 아니라 `replace_stream`(임시 파일 + os.replace)을 써서
        쓰기 중 실패해도 원본 `transactions.jsonl`은 1바이트도 바뀌지
        않는다. ID 예약(advance_by)은 쓰기 전에 처리한다. 실패하면 번호는
        건너뛰며 정상 meta.json을 유지하는 동안 예약한 번호는 재사용하지 않는다.
        """
        draft_list = list(drafts)
        start = self._seq.peek()
        records = [
            Transaction.from_draft(format_transaction_id(start + offset), draft)
            for offset, draft in enumerate(draft_list)
        ]
        if not records:
            return []
        self._seq.advance_by(len(records))
        merged = chain(
            self._store.iter_dicts(),
            (record.to_json_dict() for record in records),
        )
        self._store.replace_stream(merged)
        return records

    def iter_newest_first(
        self,
        limit: int | None = None,
        predicate: Callable[[Transaction], bool] | None = None,
    ) -> Iterator[Transaction]:
        """거래일·ID 내림차순으로 반환한다. 전체 거래는 메모리에 모으지 않는다.

        SORT_CHUNK_SIZE건씩 정렬해 임시 JSONL로 쓴 뒤 merge한다.
        run이 많으면 MERGE_WIDTH개씩 합쳐 동시 파일 수도 제한한다.
        generator를 닫거나 오류가 나면 임시 파일을 정리한다.
        """
        if limit is not None and limit < 1:
            return
        transactions = (tx for tx in self.iter_all() if predicate is None or predicate(tx))
        if limit is not None and limit <= SORT_CHUNK_SIZE:
            # 전체를 읽되, 메모리에는 지정한 개수의 최신 거래만 유지한다.
            yield from heapq.nlargest(limit, transactions, key=_transaction_order)
            return
        with tempfile.TemporaryDirectory(prefix="budget-sort-") as folder:
            directory = Path(folder)
            runs: list[Path] = []
            chunk: list[Transaction] = []
            for tx in transactions:
                chunk.append(tx)
                if len(chunk) >= SORT_CHUNK_SIZE:
                    chunk.sort(key=_transaction_order, reverse=True)
                    path = directory / f"run-{len(runs)}.jsonl"
                    _write_run(path, chunk)
                    runs.append(path)
                    chunk.clear()
            if chunk:
                chunk.sort(key=_transaction_order, reverse=True)
                path = directory / f"run-{len(runs)}.jsonl"
                _write_run(path, chunk)
                runs.append(path)
            generation = 0
            while len(runs) > MERGE_WIDTH:
                merged: list[Path] = []
                for offset in range(0, len(runs), MERGE_WIDTH):
                    batch = runs[offset:offset + MERGE_WIDTH]
                    path = directory / f"merge-{generation}-{len(merged)}.jsonl"
                    with closing(_merge_runs(batch)) as stream:
                        _write_run(path, stream)
                    merged.append(path)
                    for old in batch:
                        old.unlink()
                runs = merged
                generation += 1
            ordered = _merge_runs(runs)
            try:
                for count, tx in enumerate(ordered, start=1):
                    yield tx
                    if limit is not None and count >= limit:
                        return
            finally:
                ordered.close()

    def iter_all(self) -> Iterator[Transaction]:
        """입력 순서대로 거래를 읽는다. summary 등의 집계에 사용한다."""
        for record in self._store.iter_dicts():
            yield Transaction.from_json_dict(record)

    def update(self, tx_id: str, transform: Callable[[Transaction], Transaction]) -> Transaction:
        """해당 거래를 바꿔 임시 파일에 쓰고 교체한다. 없으면 NotFoundError."""
        return self._rewrite(tx_id, lambda tx: transform(tx))

    def remove(self, tx_id: str) -> Transaction:
        """해당 거래를 제외해 임시 파일에 쓰고 교체한다. 없으면 NotFoundError."""
        return self._rewrite(tx_id, lambda tx: None)

    def _rewrite(
        self,
        tx_id: str,
        transform: Callable[[Transaction], Transaction | None],
    ) -> Transaction:
        found_old: Transaction | None = None
        after: Transaction | None = None

        def records() -> Iterator[dict[str, object]]:
            nonlocal found_old, after
            for record in self._store.iter_dicts():
                tx = Transaction.from_json_dict(record)
                if tx.id != tx_id:
                    yield record
                    continue
                found_old = tx
                after = transform(tx)
                if after is not None:
                    yield after.to_json_dict()

        self._store.replace_stream(records())
        if found_old is None:
            raise NotFoundError(
                f"id '{tx_id}' 거래가 없습니다.",
                "list나 search로 정확한 id(TX-000001 형식)를 확인하세요.",
            )
        # update는 새 거래를, delete(transform이 None를 반환)는 지워진 거래를 돌려준다.
        return after if after is not None else found_old


class CategoryRepository:
    """categories.jsonl 담당. 이름 하나가 곧 키다."""

    def __init__(self, data_dir: Path) -> None:
        self._store = JsonlStore(data_dir / "categories.jsonl")

    def ensure_defaults(self, names: Iterable[str] = DEFAULT_CATEGORY_NAMES) -> None:
        """파일이 없거나 비었을 때만 기본 카테고리를 채운다(첫 실행)."""
        if self._store.exists():
            return
        self._store.append_many({"name": name} for name in names)

    def iter_all(self) -> list[Category]:
        return [Category.from_json_dict(record) for record in self._store.iter_dicts()]

    def contains(self, name: str) -> bool:
        wanted = name.strip()
        return any(category.name == wanted for category in self.iter_all())

    def add(self, name: str) -> Category:
        category = Category(name=name)
        if self.contains(category.name):
            raise ConflictError(
                f"카테고리 '{category.name}'는 이미 있습니다.",
                "category list로 현재 카테고리를 확인하세요.",
            )
        self._store.append(category.to_json_dict())
        return category

    def remove(self, name: str) -> Category:
        category = Category(name=name)

        def records() -> Iterator[dict[str, object]]:
            for record in self._store.iter_dicts():
                if Category.from_json_dict(record).name != category.name:
                    yield record

        existed = self.contains(category.name)
        if not existed:
            raise NotFoundError(
                f"카테고리 '{category.name}'가 없습니다.",
                "category list로 이름을 확인하세요.",
            )
        self._store.replace_stream(records())
        return category


class BudgetRepository:
    """budgets.jsonl 담당. month(YYYY-MM) 키로 한 달 한 개를 보장(upsert)."""

    def __init__(self, data_dir: Path) -> None:
        self._store = JsonlStore(data_dir / "budgets.jsonl")

    def get(self, month: str) -> Budget | None:
        for record in self._store.iter_dicts():
            budget = Budget.from_json_dict(record)
            if budget.month == month:
                return budget
        return None

    def iter_all(self) -> list[Budget]:
        budgets = [Budget.from_json_dict(record) for record in self._store.iter_dicts()]
        return sorted(budgets, key=lambda budget: budget.month)

    def upsert(self, month: str, amount: int) -> Budget:
        budget = Budget(month=month, amount=amount)

        def records() -> Iterator[dict[str, object]]:
            replaced = False
            for record in self._store.iter_dicts():
                existing = Budget.from_json_dict(record)
                if existing.month == budget.month:
                    if not replaced:
                        yield budget.to_json_dict()
                        replaced = True
                    continue
                yield record
            if not replaced:
                yield budget.to_json_dict()

        self._store.replace_stream(records())
        return budget


__all__ = [
    "BudgetRepository",
    "DEFAULT_CATEGORY_NAMES",
    "CategoryRepository",
    "TransactionRepository",
]
