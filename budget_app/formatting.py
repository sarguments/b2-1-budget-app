"""stdout 출력 문자열 만드는 순수(format-only) 모듈.

데이터(모델)와 화면 문자열을 분리해서, cli는 조립만 하고 서수는 여기 있다.
순수 함수만 담으므로 저장소/입력과 무관하게 단위 테스트로 검증하기 쉽다.
"""

from __future__ import annotations

from collections.abc import Sequence

from budget_app.models import Budget, Category, Transaction

#: list/search 행 구분자. `id | 날짜 | 타입 | 카테고리 | 금액 | 메모 [#태그,태그]`
ROW_SEPARATOR: str = " | "


def transaction_row(tx: Transaction) -> str:
    """거래 한 건을 list/search 표시 한 줄로 바꾼다."""
    row = ROW_SEPARATOR.join(
        [tx.id, tx.date, tx.type, tx.category, str(tx.amount), tx.memo]
    )
    if tx.tags:
        row = f"{row} #{','.join(tx.tags)}"
    return row


def category_row(category: Category) -> str:
    return category.name


def budget_row(budget: Budget) -> str:
    return f"{budget.month}: {budget.amount}원"


def summary_rows(
    month: str,
    income: int,
    expense: int,
    budget: Budget | None,
    top_expense: Sequence[tuple[str, int]],
) -> list[str]:
    """summary --month 출력 블록. 거래도 예산도 없을 때만 안내 한 줄만 낸다."""
    if income == 0 and expense == 0 and budget is None:
        return [f"{month}: 그 달 데이터가 없습니다."]
    rows = [
        f"{month} 요약",
        f"총 수입: {income}원",
        f"총 지출: {expense}원",
        f"잔액: {income - expense}원",
    ]
    if budget is not None:
        usage_pct = expense / budget.amount * 100.0
        rows.append(f"예산: {budget.amount}원 (사용률 {usage_pct:.1f}%)")
        if expense > budget.amount:
            rows.append(f"[경고] 예산 초과: {expense - budget.amount}원")
    if top_expense:
        rows.append(f"지출 TOP {len(top_expense)}")
        for rank, (category, amount) in enumerate(top_expense, start=1):
            rows.append(f"{rank}. {category}: {amount}원")
    return rows


__all__ = ["ROW_SEPARATOR", "budget_row", "category_row", "summary_rows", "transaction_row"]
