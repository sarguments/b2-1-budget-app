"""비즈니스 로직 집약 계층(BudgetService).

cli는 인수 해석·출력만 하고, 규칙(카테고리 등록 요건, 사용 중 카테고리
보호, 월 집계, import 부분 성공)은 전부 여기서 판단한다. 서비스 메서드에는
`@handle_errors`/`@timed`/`@logged`를 겹쳐 적용한다(decorators.py).
단, 지연 생성기(iter_*)는 데코레이터로 감싸면 '생성' 시간만 잰다고
로깅되는 문제가 있어 감싸지 않는다 — 예외는 cli 최상단에서 잡힌다.
"""

from __future__ import annotations

import csv
import os
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from budget_app.decorators import handle_errors, logged, timed
from budget_app.errors import ConflictError, ValidationError
from budget_app.models import (
    CSV_HEADER,
    CSV_REQUIRED_COLUMNS,
    Budget,
    Category,
    NewTransaction,
    Transaction,
    TransactionPatch,
    apply_patch,
)
from budget_app.repositories import (
    BudgetRepository,
    CategoryRepository,
    TransactionRepository,
)

#: import/export에서 CSV로 내보낼 컬럼(스키마 고정).
CSV_FIELDNAMES = list(CSV_HEADER)

#: data_dir 안에서 앱이 관리하는 파일명. export가 절대 덮어쓰면 안 된다(자료 유실).
_APP_DATA_FILE_NAMES: tuple[str, ...] = (
    "transactions.jsonl",
    "categories.jsonl",
    "budgets.jsonl",
    "meta.json",
)


@dataclass(frozen=True, slots=True)
class SearchCriteria:
    """search/export의 필터. 모든 조건은 AND로 결합된다(기본: 조건 없음)."""

    month: str = ""
    date_from: str = ""
    date_to: str = ""
    tx_type: str = ""
    category: str = ""
    query: str = ""
    tag: str = ""

    def matches(self, tx: Transaction) -> bool:
        if self.month and not tx.date.startswith(self.month):
            return False
        if self.date_from and tx.date < self.date_from:
            return False
        if self.date_to and tx.date > self.date_to:
            return False
        if self.tx_type and tx.type != self.tx_type:
            return False
        if self.category and tx.category != self.category:
            return False
        if self.query and self.query.lower() not in tx.memo.lower():
            return False
        if self.tag and self.tag.lower() not in (tag.lower() for tag in tx.tags):
            return False
        return True


@dataclass(frozen=True, slots=True)
class SummaryResult:
    """summary --month 계산 결과(출력 문자열화 전 데이터)."""

    month: str
    income: int
    expense: int
    budget: Budget | None
    top_expense: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ImportResult:
    """import 부분 성공 정책의 결과물. 유효행만 저장하고 나머지를 보고한다."""

    imported: int
    skipped: tuple[str, ...]


class BudgetService:
    """세 저장소를 조합하는 앱의 단일 파사드. cli는 이 것만 안다."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        self._transactions = TransactionRepository(data_dir)
        self._categories = CategoryRepository(data_dir)
        self._budgets = BudgetRepository(data_dir)

    # ---- 카테고리 -------------------------------------------------------

    @handle_errors
    def ensure_default_categories(self) -> None:
        self._categories.ensure_defaults()

    @handle_errors
    def has_category(self, name: str) -> bool:
        return self._categories.contains(name)

    @handle_errors
    @timed
    @logged
    def add_category(self, name: str) -> Category:
        return self._categories.add(name)

    @handle_errors
    def list_categories(self) -> list[Category]:
        return self._categories.iter_all()

    @handle_errors
    @timed
    @logged
    def remove_category(self, name: str) -> Category:
        category = Category(name=name)
        in_use = next(
            (tx for tx in self._transactions.iter_all() if tx.category == category.name),
            None,
        )
        if in_use is not None:
            raise ConflictError(
                f"카테고리 '{category.name}'를 사용 중인 거래가 있습니다(예: {in_use.id}).",
                "해당 거래를 update --category로 옮기거나 삭제한 뒤 다시 시도하세요.",
            )
        return self._categories.remove(category.name)

    # ---- 거래 -----------------------------------------------------------

    @handle_errors
    @timed
    @logged
    def add_transaction(self, draft: NewTransaction) -> Transaction:
        if not self._categories.contains(draft.category):
            raise ValidationError(
                f"카테고리 '{draft.category}'가 등록돼 있지 않습니다.",
                "category add 후 다시 입력하거나, 등록된 카테고리를 사용하세요.",
            )
        return self._transactions.add(draft)

    def iter_newest_first(self, limit: int) -> Iterator[Transaction]:
        """list: 역순 생성기 스트리밍. 메모리는 블록+limit 건만 사용."""
        return self._transactions.iter_newest_first(limit)

    def iter_matching(self, criteria: SearchCriteria) -> Iterator[Transaction]:
        """search: 같은 역순 생성기를 지연 필터로 거른다(전체 로드 없음)."""
        for tx in self._transactions.iter_newest_first(None):
            if criteria.matches(tx):
                yield tx

    @handle_errors
    @timed
    @logged
    def update_transaction(self, tx_id: str, patch: TransactionPatch) -> Transaction:
        if patch.category is not None and not self._categories.contains(patch.category):
            raise ValidationError(
                f"카테고리 '{patch.category}'가 등록돼 있지 않습니다.",
                "category add로 먼저 등록하세요.",
            )
        return self._transactions.update(tx_id, lambda tx: apply_patch(tx, patch))

    @handle_errors
    @timed
    @logged
    def delete_transaction(self, tx_id: str) -> Transaction:
        return self._transactions.remove(tx_id)

    # ---- 집계·예산 --------------------------------------------------------

    @handle_errors
    @timed
    @logged
    def summarize(self, month: str, top_count: int) -> SummaryResult:
        income = 0
        expense = 0
        by_category: dict[str, int] = {}
        for tx in self._transactions.iter_all():
            if not tx.date.startswith(month):
                continue
            if tx.type == "income":
                income += tx.amount
            else:
                expense += tx.amount
                by_category[tx.category] = by_category.get(tx.category, 0) + tx.amount
        ranked = sorted(by_category.items(), key=lambda item: (-item[1], item[0]))
        return SummaryResult(
            month=month,
            income=income,
            expense=expense,
            budget=self._budgets.get(month),
            top_expense=tuple(ranked[:top_count]),
        )

    @handle_errors
    @timed
    @logged
    def set_budget(self, month: str, amount: int) -> Budget:
        return self._budgets.upsert(month, amount)

    @handle_errors
    def list_budgets(self) -> list[Budget]:
        return self._budgets.iter_all()

    # ---- import/export ---------------------------------------------------

    @handle_errors
    @timed
    @logged
    def import_csv(self, path: Path) -> ImportResult:
        """부분 성공 정책: 전 줄 사전검증 → 유효 줄만 기존분과 합쳐 원자 재작성.

        잘못된 줄(형식·미등록 카테고리)은 저장하지 않고 사유를 목록으로 돌려준다.
        헤더는 고정 스키마(CSV_HEADER)여야 하며 중복 열·모르는 열은 파일 전체를
        거부한다.
        """
        drafts: list[NewTransaction] = []
        skipped: list[str] = []
        try:
            handle = path.open("r", encoding="utf-8", newline="")
        except FileNotFoundError as exc:
            raise ValidationError(
                f"import할 파일을 찾을 수 없습니다: {path}",
                "--from 경로가 맞는지 확인하세요.",
            ) from exc
        with handle:
            reader = csv.DictReader(handle)
            fieldnames = reader.fieldnames or []
            duplicated = sorted({name for name in fieldnames if fieldnames.count(name) > 1})
            if duplicated:
                raise ValidationError(
                    f"CSV 헤더에 중복된 열이 있습니다: {', '.join(duplicated)}",
                    f"헤더는 {','.join(CSV_HEADER)} 형식이어야 합니다(export 결과 사용 권장).",
                )
            unknown = [name for name in fieldnames if name not in CSV_HEADER]
            if unknown:
                raise ValidationError(
                    f"CSV에 고정 스키마에 없는 열이 있습니다: {', '.join(repr(name) for name in unknown)}",
                    f"헤더는 {','.join(CSV_HEADER)} 형식이어야 합니다(export 결과 사용 권장).",
                )
            missing = [name for name in CSV_REQUIRED_COLUMNS if name not in fieldnames]
            if missing:
                raise ValidationError(
                    f"CSV 헤더에 필수 열이 없습니다: {', '.join(missing)}",
                    f"헤더는 {','.join(CSV_HEADER)} 형식이어야 합니다(export 결과 사용 권장).",
                )
            for number, row in enumerate(reader, start=2):
                try:
                    draft = NewTransaction.from_csv_row(row)
                except ValidationError as err:
                    skipped.append(f"줄 {number}: {err.cause} (힌트: {err.hint})")
                    continue
                if not self._categories.contains(draft.category):
                    skipped.append(
                        f"줄 {number}: 카테고리 '{draft.category}' 미등록 "
                        "(힌트: category add로 먼저 등록하세요.)"
                    )
                    continue
                drafts.append(draft)
        saved = self._transactions.add_many(drafts)
        return ImportResult(imported=len(saved), skipped=tuple(skipped))

    @handle_errors
    @timed
    @logged
    def export_csv(self, path: Path, criteria: SearchCriteria) -> int:
        """조건에 맞는 거래를 CSV로 내보낸다. 임시 파일→os.replace로 원자 작성.

        `--out`이 앱 데이터 파일과 같으면 거부한다(자료 유실 방지).
        """
        resolved_out = path.resolve()
        for name in _APP_DATA_FILE_NAMES:
            if resolved_out == (self._data_dir / name).resolve():
                raise ConflictError(
                    f"export 대상이 앱 데이터 파일입니다: {name}",
                    f"자료 유실을 막기 위해 --out을 데이터 디렉터리({self._data_dir}) 밖 경로로 지정하세요.",
                )
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.parent / f"{path.name}.{os.getpid()}.tmp"
        count = 0
        try:
            with temp.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(CSV_FIELDNAMES)
                for tx in self.iter_matching(criteria):
                    writer.writerow(tx.to_csv_row())
                    count += 1
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp, path)
        except BaseException:
            temp.unlink(missing_ok=True)
            raise
        return count


__all__ = [
    "BudgetService",
    "ImportResult",
    "SearchCriteria",
    "SummaryResult",
]
