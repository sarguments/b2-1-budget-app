"""경계 형식 파서: 문자열 입력(콘솔·CSV·JSON)을 검증된 기본 값으로 바꾼다.

models.py가 '검증된 데이터 모양'이라면, 여기는 '그 모양에 도달하는 규칙'
모음이다. 실패 시 원인과 힌트를 담은 ValidationError만 던지고 통과한 값만
내보낸다. cli·models·repositories 세 계층이 같은 규칙을 공유한다.
"""

from __future__ import annotations

import re
from datetime import date as _date
from typing import Final, Literal

from budget_app.errors import ValidationError

TransactionType = Literal["income", "expense"]
TRANSACTION_TYPES: Final[tuple[TransactionType, ...]] = ("income", "expense")

_ID_PATTERN: Final = re.compile(r"^TX-\d{6}$")
_DATE_PATTERN: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_MONTH_PATTERN: Final = re.compile(r"^\d{4}-\d{2}$")

MAX_CATEGORY_LENGTH: Final = 30
MAX_MEMO_LENGTH: Final = 200


def reject_control_chars(value: str, label: str) -> None:
    """행 구분·CSV 파싱을 깨는 문자를 한 곳에서 차단한다."""
    if any(char in value for char in ("\n", "\r", "|")):
        raise ValidationError(
            f"{label}에 줄바꿈이나 구분 문자 '|'를 쓸 수 없습니다.",
            f"{label}를 한 줄·구분자 없이 입력하세요.",
        )


def parse_type(raw: str) -> TransactionType:
    """'income'/'expense' 문자열을 검증해 리터럴 값으로 돌려준다."""
    value = raw.strip().lower()
    if value == "income":
        return "income"
    if value == "expense":
        return "expense"
    raise ValidationError(
        f"타입 '{raw}'는 알 수 없습니다.",
        "income 또는 expense만 입력할 수 있습니다.",
    )


def parse_date(raw: str) -> str:
    """YYYY-MM-DD 달력 실존 날짜를 검증하고 공백을 제거한다."""
    value = raw.strip()
    if not _DATE_PATTERN.match(value):
        raise ValidationError(
            f"날짜 '{raw}'는 YYYY-MM-DD 형식이 아닙니다.",
            "예: 2024-01-15처럼 연-월-일(네자리-두자리-두자리)로 입력하세요.",
        )
    try:
        _date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError(
            f"날짜 '{value}'는 달력에 존재하지 않습니다.",
            "월(01~12)과 일 범위를 확인하세요.",
        ) from exc
    return value


def parse_month(raw: str) -> str:
    """YYYY-MM 형식(월 집계·예산 키)을 검증한다."""
    value = raw.strip()
    if not _MONTH_PATTERN.match(value):
        raise ValidationError(
            f"월 '{raw}'는 YYYY-MM 형식이 아닙니다.",
            "예: 2024-01처럼 연-월(네자리-두자리)로 입력하세요.",
        )
    try:
        _date.fromisoformat(f"{value}-01")
    except ValueError as exc:
        raise ValidationError(
            f"월 '{value}'는 달력에 존재하지 않습니다.",
            "월은 01~12 사이여야 합니다.",
        ) from exc
    return value


def parse_amount(raw: str | int) -> int:
    """양수 정수 금액만 허용한다. 문자열(콘솔/CSV 입력)과 int를 모두 받는다."""
    if isinstance(raw, bool):
        raise ValidationError("금액은 정수여야 합니다.", "15000처럼 숫자만 입력하세요.")
    if isinstance(raw, int):
        value = raw
    else:
        try:
            value = int(raw.strip())
        except ValueError as exc:
            raise ValidationError(
                f"금액 '{raw}'를 정수로 해석할 수 없습니다.",
                "쉼표·소수점 없이 양수 정수(예: 15000)로 입력하세요.",
            ) from exc
    if value <= 0:
        raise ValidationError(
            f"금액 {value}는 양수가 아닙니다.",
            "1 이상의 정수로 다시 입력하세요.",
        )
    return value


def parse_tags(raw: str) -> tuple[str, ...]:
    """쉼표 구분 태그 문자열 → 공백·빈 항목을 걸러낸 튜플(엔터=태그 없음)."""
    return normalize_tags(tuple(item.strip() for item in raw.split(",") if item.strip()))


def normalize_tags(tags: tuple[str, ...]) -> tuple[str, ...]:
    normalized = tuple(str(tag).strip() for tag in tags)
    if any(not tag for tag in normalized):
        raise ValidationError("빈 태그 항목이 있습니다.", "쉼표로 나눌 때 빈 칸만 있는 항목은 빼세요.")
    for tag in normalized:
        reject_control_chars(tag, "태그")
    return normalized


def validate_category_name(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValidationError("카테고리는 빈 값일 수 없습니다.", "food, edu 같은 카테고리를 입력하세요.")
    if len(value) > MAX_CATEGORY_LENGTH:
        raise ValidationError(
            f"카테고리 이름이 {MAX_CATEGORY_LENGTH}자를 넘습니다.",
            "더 짧은 이름으로 입력하세요.",
        )
    reject_control_chars(value, "카테고리")
    return value


def format_transaction_id(seq: int) -> str:
    """거래 id: TX- + 6자리 영(0) 채번 번호(원문 요구 형식)."""
    return f"TX-{seq:06d}"


def is_transaction_id(value: str) -> bool:
    return bool(_ID_PATTERN.match(value))


__all__ = [
    "MAX_CATEGORY_LENGTH",
    "MAX_MEMO_LENGTH",
    "TRANSACTION_TYPES",
    "TransactionType",
    "format_transaction_id",
    "is_transaction_id",
    "normalize_tags",
    "parse_amount",
    "parse_date",
    "parse_month",
    "parse_tags",
    "parse_type",
    "reject_control_chars",
    "validate_category_name",
]
