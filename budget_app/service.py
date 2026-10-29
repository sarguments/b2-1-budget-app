"""거래·카테고리·예산 규칙을 처리하는 service.

CLI는 입력과 출력을 맡고, 이 모듈은 카테고리 사용 규칙과 집계 등을 처리한다.
서비스 메서드에는 handle_errors, timed, logged decorator를 적용한다.
generator 함수(iter_*)에는 timing decorator를 적용하지 않는다.
iterator 생성 시간과 실제 순회 시간이 다르기 때문이다. 순회 중 예외는 CLI에서 처리한다.
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
    """summary --month의 집계 결과. 출력 형식은 formatting에서 처리한다."""

    month: str
    income: int
    expense: int
    budget: Budget | None
    top_expense: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class ImportResult:
    """import 결과. 저장 건수와 건너뛴 행의 사유를 담는다."""

    imported: int
    skipped: tuple[str, ...]


class BudgetService:
    """세 저장소를 조합하는 앱의 진입점. CLI는 service를 통해 repository에 접근한다."""

    def __init__(self, data_dir: Path) -> None:
        self._data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        for name in ("transactions.jsonl", "categories.jsonl", "budgets.jsonl"):
            try:
                (data_dir / name).touch(exist_ok=False)
            except FileExistsError:
                pass
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
        """list: 외부 정렬 generator로 거래일 내림차순의 거래를 반환한다."""
        return self._transactions.iter_newest_first(limit)

    def iter_matching(self, criteria: SearchCriteria) -> Iterator[Transaction]:
        """search: 거래일 내림차순으로 조건에 맞는 거래만 반환한다."""
        yield from self._transactions.iter_newest_first(None, predicate=criteria.matches)

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
        """행을 먼저 검증하고 유효한 거래를 기존 파일과 합쳐 저장한다.

        열 개수·값·카테고리가 잘못된 행은 건너뛰고 사유를 반환한다.
        필수 헤더가 없거나 중복·알 수 없는 헤더가 있으면 파일을 거부한다.
        CSV 문법·인코딩 오류도 파일 전체를 거부하며 거래를 저장하지 않는다.
        """
        drafts: list[NewTransaction] = []
        skipped: list[str] = []
        try:
            handle = path.open("r", encoding="utf-8-sig", newline="")
        except FileNotFoundError as exc:
            raise ValidationError(
                f"import할 파일을 찾을 수 없습니다: {path}",
                "--from 경로가 맞는지 확인하세요.",
            ) from exc
        try:
            with handle:
                reader = csv.DictReader(handle, strict=True)
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
                        if None in row or any(value is None for value in row.values()):
                            raise ValidationError(
                                "CSV 데이터의 열 개수가 헤더와 다릅니다.",
                                "헤더와 같은 개수의 값을 쓰고, 값 안의 쉼표는 큰따옴표로 감싸세요.",
                            )
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
        except csv.Error as exc:
            raise ValidationError(
                f"CSV 형식을 읽을 수 없습니다: {exc}",
                "따옴표와 쉼표 구분을 확인하세요. 이 파일의 거래는 저장하지 않았습니다.",
            ) from exc
        except UnicodeError as exc:
            raise ValidationError(
                "CSV 파일을 UTF-8로 읽을 수 없습니다.",
                "파일을 UTF-8로 저장한 뒤 다시 실행하세요. 이 파일의 거래는 저장하지 않았습니다.",
            ) from exc
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
