"""storage.py·repositories.py 검증: 역순 생성기, 원자 교체, 채번 단조성."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from budget_app.errors import ConflictError, NotFoundError, StorageError, ValidationError
from budget_app.models import Budget, Category, NewTransaction
from budget_app.repositories import (
    BudgetRepository,
    CategoryRepository,
    TransactionRepository,
)
from budget_app.storage import JsonlStore, SequenceFile, iter_lines_reversed


def make_draft(category: str = "food", amount: int = 1000) -> NewTransaction:
    return NewTransaction(
        type="expense", date="2024-01-15", amount=amount,
        category=category, memo="점심", tags=("meal",),
    )


class IterLinesReversedTest(unittest.TestCase):
    def _write(self, text: str) -> Path:
        fd, name = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        tmp = Path(name)
        tmp.write_text(text, encoding="utf-8")
        self.addCleanup(tmp.unlink, missing_ok=True)
        return tmp

    def test_yields_newest_first_including_korean_and_blank_lines(self) -> None:
        path = self._write("first-첫\n\nsecond-둘\nthird-셋\n")
        self.assertEqual(
            list(iter_lines_reversed(path, block_size=7)),
            ["third-셋", "second-둘", "first-첫"],
        )

    def test_block_size_one_survives_multibyte_split(self) -> None:
        path = self._write("가\n나\n다")
        self.assertEqual(list(iter_lines_reversed(path, block_size=1)), ["다", "나", "가"])

    def test_missing_file_yields_nothing(self) -> None:
        self.assertEqual(list(iter_lines_reversed(Path("/nonexistent/x.jsonl"))), [])

    def test_invalid_utf8_raises_storage_error_not_traceback(self) -> None:
        fd, name = tempfile.mkstemp(suffix=".bin")
        os.write(fd, b"\xff\xfe broken\n")
        os.close(fd)
        tmp = Path(name)
        self.addCleanup(tmp.unlink, missing_ok=True)
        with self.assertRaises(StorageError):
            list(iter_lines_reversed(tmp))


class JsonlStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "rows.jsonl"
        self.store = JsonlStore(self.path)

    def test_append_many_then_iter_forward_and_reversed(self) -> None:
        count = self.store.append_many([{"n": 1}, {"n": 2}])
        self.assertEqual(count, 2)
        self.assertEqual([r["n"] for r in self.store.iter_dicts()], [1, 2])
        self.assertEqual([r["n"] for r in self.store.iter_dicts_reversed()], [2, 1])

    def test_corrupt_line_reports_validation_error_with_hint(self) -> None:
        self.store.append({"n": 1})
        self.path.write_text("{oops\n", encoding="utf-8")
        with self.assertRaises(ValidationError) as ctx:
            list(self.store.iter_dicts())
        self.assertIn("JSON", ctx.exception.cause)

    def test_replace_stream_swaps_atomically(self) -> None:
        self.store.append_many([{"n": i} for i in range(3)])
        self.store.replace_stream({"n": i * 10} for i in range(3))
        self.assertEqual([r["n"] for r in self.store.iter_dicts()], [0, 10, 20])

    def test_replace_stream_failure_keeps_original_and_removes_temp(self) -> None:
        self.store.append_many([{"n": 1}, {"n": 2}])

        def broken_records():
            yield {"n": 99}
            raise RuntimeError("시뮬레이션 실패")

        with self.assertRaises(RuntimeError):
            self.store.replace_stream(broken_records())
        self.assertEqual([r["n"] for r in self.store.iter_dicts()], [1, 2])
        leftovers = [p.name for p in self.path.parent.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])


class SequenceFileTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.seq = SequenceFile(Path(self._dir.name) / "meta.json")

    def test_fresh_file_starts_at_one(self) -> None:
        self.assertEqual(self.seq.peek(), 1)

    def test_advance_and_advance_by_return_used_start_and_persist(self) -> None:
        self.assertEqual(self.seq.advance(), 1)
        self.assertEqual(self.seq.peek(), 2)
        self.assertEqual(self.seq.advance_by(3), 2)
        self.assertEqual(self.seq.peek(), 5)

    def test_corrupt_meta_raises_validation_error(self) -> None:
        meta = Path(self._dir.name) / "meta.json"
        meta.write_text("not-json", encoding="utf-8")
        with self.assertRaises(ValidationError):
            self.seq.peek()

    def test_missing_meta_uses_fallback_for_peek_and_advance(self) -> None:
        fallback_seq = SequenceFile(
            Path(self._dir.name) / "recovered.json", fallback=lambda: 42
        )
        self.assertEqual(fallback_seq.peek(), 42)
        self.assertEqual(fallback_seq.advance(), 42)
        self.assertEqual(fallback_seq.peek(), 43)

    def test_missing_meta_without_fallback_still_starts_at_one(self) -> None:
        empty_fallback = SequenceFile(
            Path(self._dir.name) / "none.json", fallback=lambda: None
        )
        self.assertEqual(empty_fallback.peek(), 1)


class TransactionRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.data_dir = Path(self._dir.name)
        self.repo = TransactionRepository(self.data_dir)

    def test_add_assigns_sequential_ids(self) -> None:
        first = self.repo.add(make_draft(amount=1))
        second = self.repo.add(make_draft(amount=2))
        self.assertEqual((first.id, second.id), ("TX-000001", "TX-000002"))

    def test_iter_newest_first_with_limit_reads_from_end(self) -> None:
        for i in range(1, 4):
            self.repo.add(make_draft(amount=i))
        recent = list(self.repo.iter_newest_first(2))
        self.assertEqual([tx.id for tx in recent], ["TX-000003", "TX-000002"])

    def test_delete_then_add_never_reuses_id(self) -> None:
        self.repo.add(make_draft(amount=1))
        last = self.repo.add(make_draft(amount=2))
        self.repo.remove(last.id)
        readded = self.repo.add(make_draft(amount=3))
        self.assertEqual(readded.id, "TX-000003")

    def test_update_changes_only_target(self) -> None:
        tx = self.repo.add(make_draft(amount=1))
        self.repo.add(make_draft(amount=2))
        from dataclasses import replace as dc_replace

        updated = self.repo.update(tx.id, lambda old: dc_replace(old, amount=999))
        self.assertEqual(updated.amount, 999)
        amounts = [t.amount for t in self.repo.iter_newest_first(None)]
        self.assertEqual(sorted(amounts), [2, 999])

    def test_remove_missing_id_raises_and_keeps_file(self) -> None:
        self.repo.add(make_draft(amount=1))
        with self.assertRaises(NotFoundError):
            self.repo.remove("TX-000042")
        self.assertEqual(len(list(self.repo.iter_all())), 1)

    def test_add_many_stores_all_with_sequential_ids(self) -> None:
        saved = self.repo.add_many([make_draft(amount=i) for i in (1, 2, 3)])
        self.assertEqual([tx.id for tx in saved], ["TX-000001", "TX-000002", "TX-000003"])
        self.assertEqual(len(list(self.repo.iter_all())), 3)

    def test_add_many_write_failure_keeps_transactions_byte_identical(self) -> None:
        self.repo.add(make_draft(amount=1))
        self.repo.add(make_draft(amount=2))
        tx_path = self.data_dir / "transactions.jsonl"
        before = tx_path.read_bytes()
        real_replace = os.replace

        def fail_on_transactions(src: object, dst: object) -> None:
            if str(dst).endswith("transactions.jsonl"):
                raise OSError("디스크 실패")
            real_replace(src, dst)

        with mock.patch("budget_app.storage.os.replace", side_effect=fail_on_transactions):
            with self.assertRaises(OSError):
                self.repo.add_many([make_draft(amount=3)])
        self.assertEqual(tx_path.read_bytes(), before)
        leftovers = [p.name for p in self.data_dir.iterdir() if p.name.endswith(".tmp")]
        self.assertEqual(leftovers, [])

    def test_missing_meta_recovers_sequence_from_existing_ids(self) -> None:
        for i in (1, 2, 3):
            self.repo.add(make_draft(amount=i))
        (self.data_dir / "meta.json").unlink()
        recovered = self.repo.add(make_draft(amount=4))
        self.assertEqual(recovered.id, "TX-000004")
        ids = [tx.id for tx in self.repo.iter_all()]
        self.assertEqual(len(ids), len(set(ids)))

    def test_corrupt_meta_still_raises_with_hint(self) -> None:
        self.repo.add(make_draft(amount=1))
        (self.data_dir / "meta.json").write_text("깨진 json", encoding="utf-8")
        with self.assertRaises(ValidationError) as ctx:
            self.repo.add(make_draft(amount=2))
        self.assertIn("meta.json", ctx.exception.hint)


class CategoryRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.repo = CategoryRepository(Path(self._dir.name))

    def test_ensure_defaults_only_when_empty(self) -> None:
        self.repo.ensure_defaults(("a", "b"))
        self.assertEqual([c.name for c in self.repo.iter_all()], ["a", "b"])
        self.repo.remove("b")
        # 파일이 아직 비지 않았으므로(a가 남아 있으므로) 재시드하지 않는다.
        self.repo.ensure_defaults(("a", "b"))
        self.assertFalse(self.repo.contains("b"))
        self.repo.remove("a")
        # 전부 삭제해 0바이트가 된 첫 실행 조건이면 다시 시드된다.
        self.repo.ensure_defaults(("a", "b"))
        self.assertTrue(self.repo.contains("a"))
        self.assertTrue(self.repo.contains("b"))

    def test_duplicate_add_raises_conflict(self) -> None:
        self.repo.add("food")
        with self.assertRaises(ConflictError):
            self.repo.add(" food ")

    def test_remove_streams_and_keeps_others(self) -> None:
        for name in ("a", "b", "c"):
            self.repo.add(name)
        self.repo.remove("b")
        self.assertEqual([c.name for c in self.repo.iter_all()], ["a", "c"])

    def test_remove_unknown_raises_not_found(self) -> None:
        self.repo.add("a")
        with self.assertRaises(NotFoundError):
            self.repo.remove("zzim")


class BudgetRepositoryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.repo = BudgetRepository(Path(self._dir.name))

    def test_upsert_keeps_one_per_month(self) -> None:
        self.repo.upsert("2024-01", 500000)
        self.repo.upsert("2024-02", 300000)
        self.repo.upsert("2024-01", 700000)
        budgets = self.repo.iter_all()
        self.assertEqual(len(budgets), 2)
        self.assertEqual(self.repo.get("2024-01"), Budget(month="2024-01", amount=700000))
        self.assertEqual([b.month for b in budgets], ["2024-01", "2024-02"])

    def test_get_missing_month_returns_none(self) -> None:
        self.assertIsNone(self.repo.get("2024-03"))


if __name__ == "__main__":
    unittest.main()
