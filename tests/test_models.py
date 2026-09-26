"""models.py의 경계 검증(형식·범위·일치)을 잠그는 단위 테스트."""

from __future__ import annotations

import unittest
from dataclasses import fields as _fields
from dataclasses import replace as _replace

from budget_app.errors import ValidationError
from budget_app.models import (
    Budget,
    Category,
    NewTransaction,
    Transaction,
    TransactionPatch,
    apply_patch,
)
from budget_app.parsing import (
    format_transaction_id,
    parse_amount,
    parse_date,
    parse_month,
    parse_tags,
    parse_type,
)


class ParseHelperTest(unittest.TestCase):
    def test_parse_date_accepts_real_calendar_date(self) -> None:
        self.assertEqual(parse_date(" 2024-01-15 "), "2024-01-15")

    def test_parse_date_rejects_non_iso_format(self) -> None:
        with self.assertRaises(ValidationError):
            parse_date("2024-1-5")

    def test_parse_date_rejects_impossible_day(self) -> None:
        with self.assertRaises(ValidationError):
            parse_date("2024-02-30")

    def test_parse_month_accepts_and_rejects(self) -> None:
        self.assertEqual(parse_month("2024-12"), "2024-12")
        with self.assertRaises(ValidationError):
            parse_month("2024-13")

    def test_parse_type_is_case_insensitive_and_trimmed(self) -> None:
        self.assertEqual(parse_type(" EXPENSE "), "expense")
        with self.assertRaises(ValidationError):
            parse_type("refund")

    def test_parse_amount_accepts_digits_only(self) -> None:
        self.assertEqual(parse_amount("15000"), 15000)
        self.assertEqual(parse_amount(500000), 500000)

    def test_parse_amount_rejects_non_positive_and_float(self) -> None:
        for raw in ("0", "-5", "1500.5", "abc"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValidationError):
                    parse_amount(raw)

    def test_parse_tags_strips_and_drops_empties(self) -> None:
        self.assertEqual(parse_tags(" a , ,b, "), ("a", "b"))

    def test_format_transaction_id_pads_six(self) -> None:
        self.assertEqual(format_transaction_id(1), "TX-000001")
        self.assertEqual(format_transaction_id(123456), "TX-123456")


class NewTransactionTest(unittest.TestCase):
    def _draft(self, **overrides: object) -> NewTransaction:
        base = NewTransaction(
            type="expense", date="2024-01-15", amount=15000,
            category="food", memo="점심", tags=("meal",),
        )
        return _replace(base, **overrides) if overrides else base

    def test_valid_draft_normalizes_fields(self) -> None:
        draft = NewTransaction(
            type=" expense ", date="2024-01-15", amount="15000",
            category="food", memo="  점심 ", tags=(),
        )
        self.assertEqual(draft.type, "expense")
        self.assertEqual(draft.amount, 15000)
        self.assertEqual(draft.memo, "점심")

    def test_draft_rejects_negative_amount(self) -> None:
        with self.assertRaises(ValidationError):
            self._draft(amount=-1)

    def test_draft_rejects_blank_category(self) -> None:
        with self.assertRaises(ValidationError):
            self._draft(category="   ")

    def test_draft_rejects_separator_in_memo(self) -> None:
        with self.assertRaises(ValidationError):
            self._draft(memo="a|b")

    def test_from_csv_row_parses_before_constructing(self) -> None:
        draft = NewTransaction.from_csv_row(
            {"date": "2024-01-15", "type": "expense", "category": "food", "amount": "15000"}
        )
        self.assertIsInstance(draft.amount, int)
        self.assertEqual(draft.amount, 15000)
        self.assertEqual(draft.type, "expense")

    def test_from_csv_row_still_reports_bad_amount_and_type(self) -> None:
        with self.assertRaises(ValidationError):
            NewTransaction.from_csv_row(
                {"date": "2024-01-15", "type": "expense", "category": "food", "amount": "abc"}
            )
        with self.assertRaises(ValidationError):
            NewTransaction.from_csv_row(
                {"date": "2024-01-15", "type": "oops", "category": "food", "amount": "1"}
            )

    def test_type_fields_annotated_as_transaction_type(self) -> None:
        self.assertEqual(
            {f.name: f.type for f in _fields(NewTransaction)}["type"], "TransactionType"
        )
        self.assertEqual(
            {f.name: f.type for f in _fields(Transaction)}["type"], "TransactionType"
        )
        self.assertEqual(
            {f.name: f.type for f in _fields(TransactionPatch)}["type"],
            "TransactionType | None",
        )


class TransactionTest(unittest.TestCase):
    def _draft(self) -> NewTransaction:
        return NewTransaction(
            type="expense",
            date="2024-01-15",
            amount=15000,
            category="food",
            memo="점심",
            tags=("meal",),
        )

    def test_from_draft_then_to_json_dict_roundtrip(self) -> None:
        tx = Transaction.from_draft("TX-000001", self._draft())
        data = tx.to_json_dict()
        self.assertEqual(data["id"], "TX-000001")
        self.assertEqual(data["tags"], ["meal"])
        self.assertEqual(Transaction.from_json_dict(data), tx)

    def test_transaction_rejects_malformed_id(self) -> None:
        with self.assertRaises(ValidationError):
            Transaction(id="TX-1", type="expense", date="2024-01-15", amount=1, category="etc")

    def test_from_json_dict_requires_core_fields(self) -> None:
        with self.assertRaises(ValidationError):
            Transaction.from_json_dict({"id": "TX-000001", "type": "expense"})

    def test_from_json_dict_rejects_non_integer_amount(self) -> None:
        data = {"id": "TX-000001", "type": "expense", "date": "2024-01-15",
                "amount": "15000", "category": "food"}
        with self.assertRaises(ValidationError):
            Transaction.from_json_dict(data)

    def test_csv_row_roundtrip(self) -> None:
        tx = Transaction.from_draft("TX-000002", self._draft())
        row = dict(zip(("date", "type", "category", "amount", "memo", "tags"), tx.to_csv_row()))
        self.assertEqual(Transaction.from_csv_row(row, "TX-000002"), tx)

    def test_from_csv_row_reports_missing_required_value(self) -> None:
        row = {"date": "", "type": "expense", "category": "food", "amount": "100"}
        with self.assertRaises(ValidationError) as ctx:
            Transaction.from_csv_row(row, "TX-000003")
        self.assertIn("date", ctx.exception.cause)


class TransactionPatchTest(unittest.TestCase):
    def _tx(self) -> Transaction:
        return Transaction(
            id="TX-000001", type="expense", date="2024-01-15",
            amount=15000, category="food", memo="점심", tags=("meal",),
        )

    def test_empty_patch_has_no_changes(self) -> None:
        self.assertFalse(TransactionPatch().has_changes())

    def test_apply_patch_replaces_only_given_fields(self) -> None:
        updated = apply_patch(self._tx(), TransactionPatch(amount=20000, memo=""))
        self.assertEqual(updated.amount, 20000)
        self.assertEqual(updated.memo, "")
        self.assertEqual(updated.category, "food")
        self.assertEqual(updated.tags, ("meal",))
        self.assertEqual(updated.id, "TX-000001")

    def test_patch_validation_rejects_bad_amount(self) -> None:
        with self.assertRaises(ValidationError):
            TransactionPatch(amount=0)

    def test_frozen_models_reject_mutation(self) -> None:
        with self.assertRaises(Exception):
            self._tx().amount = 1  # type: ignore[misc]


class CategoryBudgetTest(unittest.TestCase):
    def test_category_normalizes_and_json_roundtrips(self) -> None:
        category = Category(name=" robot ")
        self.assertEqual(category.name, "robot")
        self.assertEqual(Category.from_json_dict(category.to_json_dict()), category)

    def test_budget_validates_month_and_positive_amount(self) -> None:
        budget = Budget(month="2024-01", amount=500000)
        self.assertEqual(Budget.from_json_dict(budget.to_json_dict()), budget)
        with self.assertRaises(ValidationError):
            Budget(month="2024-01-15", amount=1)
        with self.assertRaises(ValidationError):
            Budget(month="2024-01", amount=-1)
        with self.assertRaises(ValidationError):
            Budget.from_json_dict({"month": "2024-01", "amount": "10"})


if __name__ == "__main__":
    unittest.main()
