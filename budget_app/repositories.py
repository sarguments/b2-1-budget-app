"""모델을 넣고 빼는 저장소(Repository) 세 개 + 채번 연결.

- TransactionRepository: 거래 추가/조회/수정/삭제. 단건 추가만 append,
  import(add_many)·수정·삭제는 스트리밍 재작성 후 os.replace 원자 교체(storage.JsonlStore.replace_stream).
- CategoryRepository: 카테고리 추가/목록/삭제, 첫 실행 기본값 자동 생성.
- BudgetRepository: 월 예산 upsert(한 달 한 개)과 목록.

저장소는 형식 검증만 모델에 맡기고, 파일 경로 규칙과 id 채번을 책임진다.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from itertools import chain
from pathlib import Path

from budget_app.errors import ConflictError, NotFoundError
from budget_app.models import Budget, Category, NewTransaction, Transaction
from budget_app.parsing import format_transaction_id, is_transaction_id
from budget_app.storage import JsonlStore, SequenceFile

#: 저장 파일이 아예 없거나 비었을 때 만드는 기본 카테고리(README 소재안).
DEFAULT_CATEGORY_NAMES: tuple[str, ...] = ("parts", "tools", "edu", "transit", "food", "etc")


class TransactionRepository:
    """transactions.jsonl 한 파일의 유일한 쓰기·읽기 창구."""

    def __init__(self, data_dir: Path) -> None:
        self._store = JsonlStore(data_dir / "transactions.jsonl")
        # meta.json 유실/비움 회복: 기존 최대 id + 1로 채번을 이어가 id 중복을 막는다.
        self._seq = SequenceFile(data_dir / "meta.json", fallback=self._recover_from_ids)

    def _recover_from_ids(self) -> int | None:
        """거래 파일의 유효한 `TX-` id 중 최대값 + 1. 거래가 없으면 None.

        meta.json이 사라졌거나 비었을 때만(SequenceFile 폴백) 호출되는
        회복 경로라 전체 순회를 감수한다. id 형식이 아닌 줄은 여기서 판단
        하지 않고 넘긴다(실제 독해 경로는 모델 검증이 잡는다).
        """
        best: int | None = None
        for record in self._store.iter_dicts():
            raw_id = record.get("id")
            if isinstance(raw_id, str) and is_transaction_id(raw_id):
                seq = int(raw_id[len("TX-"):])
                if best is None or seq >= best:
                    best = seq + 1
        return best

    def add(self, draft: NewTransaction) -> Transaction:
        """id를 채번해 한 건을 확정 저장하고 모델을 돌려준다."""
        tx = Transaction.from_draft(format_transaction_id(self._seq.peek()), draft)
        self._seq.advance()
        self._store.append(tx.to_json_dict())
        return tx

    def add_many(self, drafts: Iterable[NewTransaction]) -> list[Transaction]:
        """초안을 전부 검증한 뒤, 기존분+유효분을 스트리밍 재작성으로 원자 추가.

        append가 아니라 `replace_stream`(임시 파일 + os.replace)을 써서
        쓰기 중 실패해도 원본 `transactions.jsonl`은 1바이트도 바뀌지
        않는다. 채번 확정(advance_by)은 쓰기 앞에 두고 실패 시 번호는
        건너뛸 뿐 재사용되지 않는다(id 단조 증가 유지).
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

    def iter_newest_first(self, limit: int | None = None) -> Iterator[Transaction]:
        """역순 생성기로 최신 추가분부터 유한 메모리 순회. limit건에서 중단."""
        count = 0
        for record in self._store.iter_dicts_reversed():
            yield Transaction.from_json_dict(record)
            count += 1
            if limit is not None and count >= limit:
                return

    def iter_all(self) -> Iterator[Transaction]:
        """추가된 순서(파일 순) 전체 순회. summary처럼 최신순이 의미 없는 곳에 쓴다."""
        for record in self._store.iter_dicts():
            yield Transaction.from_json_dict(record)

    def update(self, tx_id: str, transform: Callable[[Transaction], Transaction]) -> Transaction:
        """한 건만 고치는 스트리밍 재작성 + 원자 교체. 없으면 NotFoundError."""
        return self._rewrite(tx_id, lambda tx: transform(tx))

    def remove(self, tx_id: str) -> Transaction:
        """한 건을 빼는 스트리밍 재작성 + 원자 교체. 없으면 NotFoundError."""
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
