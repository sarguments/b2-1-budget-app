"""stdout에 출력할 문자열을 만드는 모듈.

모델 데이터의 출력 형식은 이 모듈에서 정의하고, CLI는 결과를 출력한다.
파일이나 입력 상태를 바꾸지 않는 순수 함수로 구성한다.
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
    """summary --month 출력 블록. 거래와 예산이 모두 없으면 안내 문구만 반환한다."""
    if income == 0 and expense == 0 and budget is None:
        return [f"{month}: 그 달 데이터가 없습니다."]
    rows = [
        f"{month} 요약",
        f"총 수입: {income}원",
        f"총 지출: {expense}원",
        f"잔액: {income - expense}원",
    ]
    if income == 0 and expense == 0:
        rows.append("해당 월 거래가 없습니다.")
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
