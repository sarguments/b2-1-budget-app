"""CLI 종단간(end-to-end) 테스트: 실제 프로세스로 10개 명령·오류 코드·영속성 검증.

`.venv/bin/python -m budget_app`을 임시 --data-dir 대상으로 subprocess로
실행하므로, 스택 트레이스 없이 [오류]/[힌트]가 뜨는지와 프로세스 간
데이터 지속(재시작)까지 함께 확인한다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


class CliProcessMixin(unittest.TestCase):
    def setUp(self) -> None:
        self.data_dir = Path(tempfile.mkdtemp(prefix="b21-cli-"))
        self.addCleanup(shutil.rmtree, self.data_dir, True)
        self.csv_dir = Path(tempfile.mkdtemp(prefix="b21-csv-"))
        self.addCleanup(shutil.rmtree, self.csv_dir, True)

    def run_cli(self, *args: str, stdin: str = "", verbose: bool = False) -> subprocess.CompletedProcess[str]:
        cmd = [sys.executable, "-m", "budget_app"]
        if verbose:
            cmd.append("--verbose")
        cmd += ["--data-dir", str(self.data_dir), *args]
        proc = subprocess.run(
            cmd, input=stdin, capture_output=True, text=True,
            cwd=REPO_ROOT, timeout=30, check=False,
        )
        if not verbose:
            self.assertNotIn("Traceback", proc.stdout, "stdout에 트레이스가 섞였다")
            self.assertNotIn("Traceback", proc.stderr, "stderr에 트레이스가 섞였다")
        return proc

    def add_tx(self, fields: str) -> subprocess.CompletedProcess[str]:
        return self.run_cli("add", stdin=fields)


class HelpAndSeedTest(CliProcessMixin):
    def test_root_help_lists_all_commands(self) -> None:
        proc = self.run_cli("--help")
        self.assertEqual(proc.returncode, 0)
        for command in ("add", "list", "search", "summary", "budget", "category",
                        "update", "delete", "import", "export"):
            self.assertIn(command, proc.stdout)

    def test_every_subcommand_help_exits_zero(self) -> None:
        for args in (
            ("add", "--help"), ("list", "--help"), ("search", "--help"),
            ("summary", "--help"), ("budget", "set", "--help"),
            ("category", "remove", "--help"), ("update", "--help"),
            ("delete", "--help"), ("import", "--help"), ("export", "--help"),
        ):
            with self.subTest(args=args):
                self.assertEqual(self.run_cli(*args).returncode, 0)

    def test_first_run_category_list_seeds_defaults(self) -> None:
        proc = self.run_cli("category", "list")
        self.assertEqual(proc.returncode, 0)
        for name in ("parts", "tools", "edu", "transit", "food", "etc"):
            self.assertIn(name, proc.stdout)


class AddListPersistenceTest(CliProcessMixin):
    FIELDS = "2024-01-15\nexpense\nfood\n15000\n점심\nmeal\n"

    def test_add_prints_saved_with_sequential_id(self) -> None:
        proc = self.add_tx(self.FIELDS)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[저장 완료] id=TX-000001", proc.stdout)

    def test_list_row_format_and_persistence_across_processes(self) -> None:
        self.add_tx(self.FIELDS)
        proc = self.run_cli("list", "--limit", "3")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("TX-000001 | 2024-01-15 | expense | food | 15000 | 점심 #meal", proc.stdout)

    def test_invalid_add_reprompts_then_eof_exits_one(self) -> None:
        proc = self.add_tx("2024-13-40\nexpense\nfood\n-5\nx\ny\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[오류]", proc.stdout)
        self.assertIn("[힌트]", proc.stdout)

    def test_unregistered_category_blocks_add(self) -> None:
        proc = self.add_tx("2024-01-15\nexpense\n유령\n100\nm\n\n")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("등록된 카테고리가 아닙니다", proc.stdout)

    def test_ids_keep_monotonic_after_delete(self) -> None:
        self.add_tx("2024-01-15\nexpense\nfood\n100\na\n\n")
        self.add_tx("2024-01-16\nexpense\nfood\n200\nb\n\n")
        self.run_cli("delete", "--id", "TX-000002")
        proc = self.add_tx("2024-01-17\nexpense\nfood\n300\nc\n\n")
        self.assertIn("id=TX-000003", proc.stdout)

    def test_missing_meta_recovers_ids_from_existing_transactions(self) -> None:
        for memo in ("a", "b", "c"):
            self.add_tx(f"2024-01-15\nexpense\nfood\n100\n{memo}\n\n")
        (self.data_dir / "meta.json").unlink()
        proc = self.add_tx("2024-01-16\nexpense\nfood\n400\nd\n\n")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("id=TX-000004", proc.stdout)
        listed = self.run_cli("list", "--limit", "10").stdout
        ids = [line.split(" | ")[0] for line in listed.splitlines() if line.startswith("TX-")]
        self.assertEqual(len(ids), len(set(ids)))


class SearchSummaryBudgetTest(CliProcessMixin):
    def setUp(self) -> None:
        super().setUp()
        self.add_tx("2024-01-15\nexpense\nfood\n15000\n점심 예약\nmeal,lunch\n")
        self.add_tx("2024-01-20\nexpense\nedu\n30000\n로봇 강의\nstudy\n")
        self.add_tx("2024-02-01\nincome\netc\n20000\n용돈\n\n")

    def test_search_combines_filters_with_and(self) -> None:
        proc = self.run_cli("search", "--from", "2024-01-01", "--to", "2024-01-31",
                            "--type", "expense", "--category", "edu")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("로봇 강의", proc.stdout)
        self.assertNotIn("점심", proc.stdout)

    def test_search_query_matches_memo_case_insensitively(self) -> None:
        proc = self.run_cli("search", "--q", "MEAL")
        self.assertEqual(proc.returncode, 0)
        self.assertNotIn("TX-", proc.stdout)
        proc = self.run_cli("search", "--q", "점심")
        self.assertIn("TX-000001", proc.stdout)

    def test_search_tag_filter(self) -> None:
        proc = self.run_cli("search", "--tag", "study")
        self.assertIn("TX-000002", proc.stdout)

    def test_summary_shows_budget_usage_and_top(self) -> None:
        self.run_cli("budget", "set", "--month", "2024-01", "--amount", "40000")
        proc = self.run_cli("summary", "--month", "2024-01", "--top", "3")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("총 지출: 45000원", proc.stdout)
        self.assertIn("예산: 40000원 (사용률 112.5%)", proc.stdout)
        self.assertIn("[경고] 예산 초과: 5000원", proc.stdout)
        self.assertIn("지출 TOP 2", proc.stdout)

    def test_summary_for_empty_month_exits_zero_with_message(self) -> None:
        proc = self.run_cli("summary", "--month", "2099-01")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("없습니다", proc.stdout)

    def test_summary_shows_budget_even_without_transactions(self) -> None:
        self.run_cli("budget", "set", "--month", "2099-05", "--amount", "10000")
        proc = self.run_cli("summary", "--month", "2099-05")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("총 수입: 0원", proc.stdout)
        self.assertIn("예산: 10000원 (사용률 0.0%)", proc.stdout)
        self.assertNotIn("데이터가 없습니다", proc.stdout)

    def test_budget_list_shows_set_month(self) -> None:
        self.run_cli("budget", "set", "--month", "2024-01", "--amount", "500000")
        proc = self.run_cli("budget", "list")
        self.assertIn("2024-01: 500000원", proc.stdout)


class CategoryPolicyTest(CliProcessMixin):
    def test_category_add_and_remove_cycle(self) -> None:
        proc = self.run_cli("category", "add", "robot")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("카테고리 'robot'", proc.stdout)
        proc = self.run_cli("category", "remove", "robot")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[삭제 완료]", proc.stdout)

    def test_deleting_all_categories_reseeds_on_next_seed_command(self) -> None:
        for name in ("parts", "tools", "edu", "transit", "food", "etc"):
            self.assertEqual(self.run_cli("category", "remove", name).returncode, 0)
        # 전부 지우면 categories.jsonl이 0바이트가 된다(첫 실행 시드 조건과 같아짐).
        self.assertEqual((self.data_dir / "categories.jsonl").stat().st_size, 0)
        self.run_cli("category", "add", "robot")
        listed = self.run_cli("category", "list").stdout
        for name in ("parts", "tools", "edu", "transit", "food", "etc", "robot"):
            self.assertIn(name, listed)

    def test_remove_in_use_category_is_blocked(self) -> None:
        self.add_tx("2024-01-15\nexpense\nfood\n1000\nm\n\n")
        proc = self.run_cli("category", "remove", "food")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[오류]", proc.stdout)
        self.assertIn("사용 중인 거래", proc.stdout)

    def test_duplicate_category_conflict(self) -> None:
        proc = self.run_cli("category", "add", "food")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("이미 있습니다", proc.stdout)


class UpdateDeleteTest(CliProcessMixin):
    def setUp(self) -> None:
        super().setUp()
        self.add_tx("2024-01-15\nexpense\nfood\n15000\n점심\nmeal\n")

    def test_update_changes_only_given_fields(self) -> None:
        proc = self.run_cli("update", "--id", "TX-000001", "--amount", "12000", "--memo", "")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("12000", proc.stdout)
        shown = self.run_cli("list").stdout
        self.assertIn("TX-000001 | 2024-01-15 | expense | food | 12000 |  #meal", shown)

    def test_update_without_fields_is_usage_error(self) -> None:
        proc = self.run_cli("update", "--id", "TX-000001")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("[오류]", proc.stdout)

    def test_update_missing_id_is_domain_error(self) -> None:
        proc = self.run_cli("update", "--id", "", "--memo", "x")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("거래 id가 지정되지 않았습니다", proc.stdout)

    def test_update_unknown_id_not_found(self) -> None:
        proc = self.run_cli("update", "--id", "TX-999999", "--amount", "1")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[오류]", proc.stdout)

    def test_delete_reports_completion_and_persists(self) -> None:
        proc = self.run_cli("delete", "--id", "TX-000001")
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[삭제 완료] id=TX-000001", proc.stdout)
        self.assertIn("거래가 없습니다", self.run_cli("list").stdout)

    def test_delete_missing_id_exit_one(self) -> None:
        proc = self.run_cli("delete", "--id", "TX-999999")
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[힌트]", proc.stdout)


class ImportExportTest(CliProcessMixin):
    def test_export_requires_condition(self) -> None:
        proc = self.run_cli("export", "--out", str(self.csv_dir / "x.csv"))
        self.assertEqual(proc.returncode, 2)
        self.assertIn("export 조건이 없습니다", proc.stdout)

    def test_export_writes_schema_header_then_import_roundtrip(self) -> None:
        self.add_tx("2024-01-15\nexpense\nfood\n15000\n점심\nmeal\n")
        out = self.csv_dir / "out.csv"
        proc = self.run_cli("export", "--out", str(out), "--month", "2024-01")
        self.assertEqual(proc.returncode, 0)
        self.assertIn(f"[완료] {out} (1 records)", proc.stdout)
        first_line = out.read_text(encoding="utf-8").splitlines()[0]
        self.assertEqual(first_line, "date,type,category,amount,memo,tags")
        proc = self.run_cli("import", "--from", str(out))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[완료] imported=1, skipped=0", proc.stdout)
        self.assertEqual(len(self.run_cli("list").stdout.splitlines()), 2)

    def test_partial_import_stores_valid_skips_invalid(self) -> None:
        bad = self.csv_dir / "bad.csv"
        bad.write_text(
            "date,type,category,amount,memo,tags\n"
            "2024-03-01,expense,edu,30000,강의,study\n"
            "2024-03-02,expense,ghost,100,,\n"
            "bad-date,expense,food,-5,,\n",
            encoding="utf-8",
        )
        proc = self.run_cli("import", "--from", str(bad))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[완료] imported=1, skipped=2", proc.stdout)
        self.assertIn("미등록", proc.stdout)
        shown = self.run_cli("list").stdout
        self.assertIn("강의", shown)
        self.assertNotIn("ghost", shown)

    def test_import_missing_header_fails_with_hint(self) -> None:
        bad = self.csv_dir / "nohdr.csv"
        bad.write_text("a,b\n1,2\n", encoding="utf-8")
        proc = self.run_cli("import", "--from", str(bad))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[힌트]", proc.stdout)

    def test_export_refuses_to_overwrite_app_data_files(self) -> None:
        self.add_tx("2024-01-15\nexpense\nfood\n15000\n점심\nmeal\n")
        for name in ("transactions.jsonl", "categories.jsonl", "budgets.jsonl", "meta.json"):
            with self.subTest(name=name):
                target = self.data_dir / name
                if not target.exists():
                    target.write_bytes(b"sentinel\n")
                before = target.read_bytes()
                proc = self.run_cli("export", "--out", str(target), "--month", "2024-01")
                self.assertEqual(proc.returncode, 1)
                self.assertIn("[오류]", proc.stdout)
                self.assertIn("[힌트]", proc.stdout)
                self.assertEqual(target.read_bytes(), before)

    def test_import_of_all_invalid_rows_exits_one(self) -> None:
        bad = self.csv_dir / "allbad.csv"
        bad.write_text(
            "date,type,category,amount,memo,tags\n"
            "2024-03-02,expense,ghost,100,,\n"
            "bad-date,expense,food,-5,,\n",
            encoding="utf-8",
        )
        proc = self.run_cli("import", "--from", str(bad))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[완료] imported=0, skipped=2", proc.stdout)
        self.assertIn("[오류]", proc.stdout)
        self.assertIn("[힌트]", proc.stdout)
        self.assertIn("거래가 없습니다", self.run_cli("list").stdout)

    def test_import_mixed_result_still_exits_zero(self) -> None:
        mixed = self.csv_dir / "mixed.csv"
        mixed.write_text(
            "date,type,category,amount,memo,tags\n"
            "2024-03-01,expense,edu,30000,강의,study\n"
            "2024-03-02,expense,ghost,100,,\n",
            encoding="utf-8",
        )
        proc = self.run_cli("import", "--from", str(mixed))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[완료] imported=1, skipped=1", proc.stdout)
        self.assertNotIn("[오류]", proc.stdout)

    def test_import_rejects_duplicate_column(self) -> None:
        dup = self.csv_dir / "dup.csv"
        dup.write_text(
            "date,type,category,amount,memo,memo\n"
            "2024-03-01,expense,food,1000,메모,메모2\n",
            encoding="utf-8",
        )
        proc = self.run_cli("import", "--from", str(dup))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[오류]", proc.stdout)
        self.assertIn("중복", proc.stdout)

    def test_import_rejects_unknown_column(self) -> None:
        extra = self.csv_dir / "extra.csv"
        extra.write_text(
            "date,type,category,amount,extra\n"
            "2024-03-01,expense,food,1000,무언가\n",
            encoding="utf-8",
        )
        proc = self.run_cli("import", "--from", str(extra))
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[오류]", proc.stdout)
        self.assertIn("[힌트]", proc.stdout)

    def test_import_accepts_minimal_four_column_schema(self) -> None:
        minimal = self.csv_dir / "minimal.csv"
        minimal.write_text(
            "date,type,category,amount\n"
            "2024-03-01,expense,food,1000\n",
            encoding="utf-8",
        )
        proc = self.run_cli("import", "--from", str(minimal))
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[완료] imported=1, skipped=0", proc.stdout)


class UsageAndVerboseTest(CliProcessMixin):
    def test_unknown_command_exits_two_without_traceback(self) -> None:
        proc = self.run_cli("timemachine")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("[오류]", proc.stdout)

    def test_bad_option_value_exits_two(self) -> None:
        proc = self.run_cli("list", "--limit", "abc")
        self.assertEqual(proc.returncode, 2)

    def test_verbose_writes_decorator_logs_to_stderr_only(self) -> None:
        proc = self.run_cli("budget", "set", "--month", "2024-01", "--amount", "500000", verbose=True)
        self.assertEqual(proc.returncode, 0)
        self.assertIn("[로그]", proc.stderr)
        self.assertNotIn("[로그]", proc.stdout)

    def test_forced_read_error_has_no_traceback_even_verbose(self) -> None:
        (self.data_dir / "transactions.jsonl").mkdir()
        proc = self.run_cli("list", "--limit", "5", verbose=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("[오류]", proc.stdout)
        self.assertIn("[힌트]", proc.stdout)
        self.assertNotIn("Traceback", proc.stderr)
        self.assertNotIn("Traceback", proc.stdout)


if __name__ == "__main__":
    unittest.main()
