"""용돈 기입장 검증된 데이터 모델.

필드의 '형식 규칙'은 parsing.py에 있고, 이 파일은 규칙을 통과한 값만 담는
불변 모양(frozen dataclass)을 정의한다. 모델 생성 시점(`__post_init__`)에
한 번 더 검증하므로, 저장/검색 코드 이후에서는 타입·범위가 보장된 값만
다룬다(parse-don't-validate). 변경은 항상 새 객체 생성(dataclasses.replace).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Mapping

from budget_app.errors import ValidationError
from budget_app.parsing import (
    MAX_MEMO_LENGTH,
    TransactionType,
    is_transaction_id,
    normalize_tags,
    parse_amount,
    parse_date,
    parse_month,
    parse_tags,
    parse_type,
    reject_control_chars,
    validate_category_name,
)

#: import/export CSV의 고정 헤더(원문 요구 스키마).
CSV_HEADER = ("date", "type", "category", "amount", "memo", "tags")
#: CSV에서 반드시 있어야 하는 필수 열. memo/tags는 없으면 빈값으로 본다.
CSV_REQUIRED_COLUMNS = ("date", "type", "category", "amount")


@dataclass(frozen=True, slots=True)
class NewTransaction:
    """id 배정 전 거래 초안. 저장소가 id를 붙여 `Transaction`으로 승격한다."""

    type: TransactionType
    date: str
    amount: int
    category: str
    memo: str = ""
    tags: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", parse_type(self.type))
        object.__setattr__(self, "date", parse_date(self.date))
        object.__setattr__(self, "amount", parse_amount(self.amount))
        object.__setattr__(self, "category", validate_category_name(self.category))
        object.__setattr__(self, "memo", self.memo.strip())
        object.__setattr__(self, "tags", normalize_tags(self.tags))
        reject_control_chars(self.memo, "메모")
        if len(self.memo) > MAX_MEMO_LENGTH:
            raise ValidationError(
                f"메모가 {MAX_MEMO_LENGTH}자를 넘습니다.",
                "메모는 짧게 요약해 다시 입력하세요.",
            )

    @classmethod
    def from_csv_row(cls, row: Mapping[str, object]) -> "NewTransaction":
        """import CSV 한 줄 → 초안. 필수 열 결손·형식 오류는 ValidationError.

        생성자에 원문 문자열을 넘기지 않고 경계에서 먼저 파싱해, 필드
        애너테이션(int·TransactionType)과 실제 값 타입을 맞춘다.
        """
        missing = [
            key for key in CSV_REQUIRED_COLUMNS
            if key not in row or row[key] is None or str(row[key]).strip() == ""
        ]
        if missing:
            raise ValidationError(
                f"필수 값이 없습니다: {', '.join(missing)}",
                "CSV의 date/type/category/amount 열을 채우세요.",
            )
        return cls(
            type=parse_type(str(row["type"])),
            date=parse_date(str(row["date"])),
            amount=parse_amount(str(row["amount"])),
            category=validate_category_name(str(row["category"])),
            memo=str(row.get("memo") or ""),
            tags=parse_tags(str(row.get("tags") or "")),
        )


@dataclass(frozen=True, slots=True)
class Transaction:
    """저장소에 한 줄로 저장된 용돈 거래. id는 저장소가 채번한 문자열(TX-000001)."""

    id: str
    type: TransactionType
    date: str
    amount: int
    category: str
    memo: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not is_transaction_id(self.id):
            raise ValidationError(
                f"거래 id '{self.id}'가 TX-000001 형식이 아닙니다.",
                "저장 파일의 id 열을 확인하거나 해당 줄을 정리하세요.",
            )
        draft = NewTransaction(
            type=self.type,
            date=self.date,
            amount=self.amount,
            category=self.category,
            memo=self.memo,
            tags=self.tags,
        )
        object.__setattr__(self, "type", draft.type)
        object.__setattr__(self, "date", draft.date)
        object.__setattr__(self, "amount", draft.amount)
        object.__setattr__(self, "category", draft.category)
        object.__setattr__(self, "memo", draft.memo)
        object.__setattr__(self, "tags", draft.tags)

    @classmethod
    def from_draft(cls, tx_id: str, draft: NewTransaction) -> "Transaction":
        return cls(
            id=tx_id,
            type=draft.type,
            date=draft.date,
            amount=draft.amount,
            category=draft.category,
            memo=draft.memo,
            tags=draft.tags,
        )

    def to_json_dict(self) -> dict[str, object]:
        """JSONL 저장용 dict. 키 순서는 이 순서 그대로 고정한다."""
        return {
            "id": self.id,
            "type": self.type,
            "date": self.date,
            "amount": self.amount,
            "category": self.category,
            "memo": self.memo,
            "tags": list(self.tags),
        }

    @classmethod
    def from_json_dict(cls, data: Mapping[str, object]) -> "Transaction":
        """JSONL 한 줄을 해석해 모델을 만든다. 형식 오류는 ValidationError."""
        missing = [key for key in ("id", "type", "date", "amount", "category") if key not in data]
        if missing:
            raise ValidationError(
                f"거래 레코드에 필수 필드가 없습니다: {', '.join(missing)}",
                "transactions.jsonl의 손상된 줄을 확인하거나 삭제하세요.",
            )
        if not isinstance(data["amount"], int) or isinstance(data["amount"], bool):
            raise ValidationError(
                f"저장된 금액 값이 정수가 아닙니다: {data['amount']!r}",
                "transactions.jsonl의 amount 열을 확인하세요.",
            )
        raw_tags = data.get("tags", [])
        if not isinstance(raw_tags, list):
            raise ValidationError(
                "tags는 문자열 목록이어야 합니다.",
                "transactions.jsonl의 tags 열을 확인하세요.",
            )
        return cls(
            id=str(data["id"]),
            type=str(data["type"]),
            date=str(data["date"]),
            amount=int(data["amount"]),
            category=str(data["category"]),
            memo=str(data.get("memo", "")),
            tags=tuple(str(tag) for tag in raw_tags),
        )

    def to_csv_row(self) -> list[str]:
        """export CSV 한 줄(헤더 스키마와 동일, id 제외)."""
        return [
            self.date,
            self.type,
            self.category,
            str(self.amount),
            self.memo,
            ",".join(self.tags),
        ]

    @classmethod
    def from_csv_row(cls, row: Mapping[str, object], tx_id: str) -> "Transaction":
        """import CSV 한 줄 → 확정 거래. 검증은 NewTransaction.from_csv_row가 맡는다."""
        return cls.from_draft(tx_id, NewTransaction.from_csv_row(row))


@dataclass(frozen=True, slots=True)
class Category:
    """지출/수입 분류 이름. 거래·예산과 별개로 카테고리 파일에 저장된다."""

    name: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", validate_category_name(self.name))

    def to_json_dict(self) -> dict[str, object]:
        return {"name": self.name}

    @classmethod
    def from_json_dict(cls, data: Mapping[str, object]) -> "Category":
        if "name" not in data or data["name"] is None:
            raise ValidationError(
                "카테고리 레코드에 name이 없습니다.",
                "categories.jsonl의 손상된 줄을 확인하거나 삭제하세요.",
            )
        return cls(name=str(data["name"]))


@dataclass(frozen=True, slots=True)
class Budget:
    """월별 지출 예산. month(YYYY-MM)가 키며 한 달에 하나만 존재한다."""

    month: str
    amount: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "month", parse_month(self.month))
        object.__setattr__(self, "amount", parse_amount(self.amount))

    def to_json_dict(self) -> dict[str, object]:
        return {"month": self.month, "amount": self.amount}

    @classmethod
    def from_json_dict(cls, data: Mapping[str, object]) -> "Budget":
        missing = [key for key in ("month", "amount") if key not in data]
        if missing:
            raise ValidationError(
                f"예산 레코드에 필수 필드가 없습니다: {', '.join(missing)}",
                "budgets.jsonl의 손상된 줄을 확인하거나 삭제하세요.",
            )
        if not isinstance(data["amount"], int) or isinstance(data["amount"], bool):
            raise ValidationError(
                f"예산 금액이 정수가 아닙니다: {data['amount']!r}",
                "budgets.jsonl의 amount 열을 확인하세요.",
            )
        return cls(month=str(data["month"]), amount=int(data["amount"]))


@dataclass(frozen=True, slots=True)
class TransactionPatch:
    """update 명령의 변경분. None이 아닌 필드만 교체한다(옵션 기반 수정)."""

    date: str | None = None
    type: TransactionType | None = None
    category: str | None = None
    amount: int | None = None
    memo: str | None = None
    tags: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if self.date is not None:
            object.__setattr__(self, "date", parse_date(self.date))
        if self.type is not None:
            object.__setattr__(self, "type", parse_type(self.type))
        if self.category is not None:
            object.__setattr__(self, "category", validate_category_name(self.category))
        if self.amount is not None:
            object.__setattr__(self, "amount", parse_amount(self.amount))
        if self.memo is not None:
            object.__setattr__(self, "memo", self.memo.strip())
        if self.tags is not None:
            object.__setattr__(self, "tags", normalize_tags(self.tags))

    def has_changes(self) -> bool:
        return any(
            value is not None
            for value in (self.date, self.type, self.category, self.amount, self.memo, self.tags)
        )


def apply_patch(tx: Transaction, patch: TransactionPatch) -> Transaction:
    """update 명령의 옵션 기반 변경: 주어진 필드만 고쳐 새 거래를 만든다."""
    return replace(
        tx,
        date=tx.date if patch.date is None else patch.date,
        type=tx.type if patch.type is None else patch.type,
        category=tx.category if patch.category is None else patch.category,
        amount=tx.amount if patch.amount is None else patch.amount,
        memo=tx.memo if patch.memo is None else patch.memo,
        tags=tx.tags if patch.tags is None else patch.tags,
    )


__all__ = [
    "Budget",
    "CSV_HEADER",
    "CSV_REQUIRED_COLUMNS",
    "Category",
    "NewTransaction",
    "Transaction",
    "TransactionPatch",
    "apply_patch",
]
