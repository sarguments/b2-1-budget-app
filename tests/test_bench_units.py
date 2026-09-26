"""scripts/bench_100k.py의 ru_maxrss 단위 정규화 회귀 테스트.

macOS/BSD는 바이트, Linux는 KiB로 보고하는 OS 차이를 흡수하는지 확인한다.
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
_BENCH_PATH = REPO_ROOT / "scripts" / "bench_100k.py"
_spec = importlib.util.spec_from_file_location("bench_100k_under_test", _BENCH_PATH)
assert _spec is not None and _spec.loader is not None
bench = importlib.util.module_from_spec(_spec)
sys.modules["bench_100k_under_test"] = bench
_spec.loader.exec_module(bench)


class ChildRssUnitsTest(unittest.TestCase):
    def test_linux_kib_is_scaled_to_bytes(self) -> None:
        self.assertEqual(bench.child_rss_bytes(19_000, "linux"), 19_000 * 1024)

    def test_darwin_bytes_are_passed_through(self) -> None:
        self.assertEqual(bench.child_rss_bytes(19_000_000, "darwin"), 19_000_000)

    def test_same_physical_usage_normalizes_equal_across_platforms(self) -> None:
        self.assertEqual(
            bench.child_rss_bytes(19_000, "linux"),
            bench.child_rss_bytes(19_000 * 1024, "darwin"),
        )


if __name__ == "__main__":
    unittest.main()
