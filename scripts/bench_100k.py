"""100,000건 실측 벤치(표준 라이브러리만 사용).

임시 디렉터리에 거래 10만 건을 만들어 두고 실제 CLI 프로세스로
`list --limit 5`와 `search` 걸림 시간을 쟌다. 자식 프로세스 최대 RSS로
역순 생성기가 메모리를 절약하는지도 함께 보고한다. 저장소 안 `data/`는
건드리지 않는다.

실행: .venv/bin/python scripts/bench_100k.py
"""

from __future__ import annotations

import json
import random
import resource
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from datetime import date, timedelta

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from budget_app.repositories import TransactionRepository  # noqa: E402
from budget_app.models import NewTransaction  # noqa: E402

TOTAL = 100_000
CATEGORIES = ("parts", "tools", "edu", "transit", "food", "etc")


def generate(data_dir: Path, rng: random.Random) -> None:
    """저장 포맷(JSONL·메타)을 직접 만들어 10만 건을 준비한다."""
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "categories.jsonl").write_text(
        "".join(json.dumps({"name": n}, ensure_ascii=False) + "\n" for n in CATEGORIES),
        encoding="utf-8",
    )
    start = date(2023, 1, 1)
    with (data_dir / "transactions.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        lines = []
        for seq in range(1, TOTAL + 1):
            day = start + timedelta(days=rng.randrange(730))
            lines.append(json.dumps({
                "id": f"TX-{seq:06d}",
                "type": "income" if seq % 5 == 0 else "expense",
                "date": day.isoformat(),
                "amount": rng.randrange(500, 50_001),
                "category": CATEGORIES[seq % len(CATEGORIES)],
                "memo": f"로봇 자재 구매 {seq}" if seq % 3 else f"강좌 결제 {seq}",
                "tags": ["bench"] if seq % 7 == 0 else [],
            }, ensure_ascii=False) + "\n")
        handle.writelines(lines)
        handle.flush()
    (data_dir / "meta.json").write_text(json.dumps({"next_seq": TOTAL + 1}), encoding="utf-8")


def child_rss_bytes(raw: int, platform: str = sys.platform) -> int:
    """ru_maxrss 값을 바이트로 정규화한다.

    macOS/BSD는 바이트, Linux는 KiB로 보고하므로 같은 숫자가 OS마다 1024배
    다른 의미가 된다. 정규화 없이 그대로 찍으면 리눅스에서 1/1024로 보인다.
    """
    return raw * 1024 if platform.startswith("linux") else raw


def run_cli_timed(data_dir: Path, *args: str) -> tuple[float, int]:
    cmd = [sys.executable, "-m", "budget_app", "--data-dir", str(data_dir), *args]
    started = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True, cwd=REPO_ROOT,
                          timeout=120, check=False)
    elapsed = time.perf_counter() - started
    if proc.returncode != 0:
        raise SystemExit(f"벤치 실패({args}): exit={proc.returncode}\n{proc.stdout}{proc.stderr}")
    return elapsed, proc.returncode


def main() -> int:
    rng = random.Random(42)
    data_dir = Path(tempfile.mkdtemp(prefix="b21-bench-"))
    try:
        started = time.perf_counter()
        generate(data_dir, rng)
        gen_elapsed = time.perf_counter() - started
        size_mb = (data_dir / "transactions.jsonl").stat().st_size / 1024 / 1024
        print(f"생성: 거래 {TOTAL:,}건 / 파일 {size_mb:.1f}MiB / {gen_elapsed:.2f}초")

        rss_before = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        list_elapsed, _ = run_cli_timed(data_dir, "list", "--limit", "5")
        search_elapsed, _ = run_cli_timed(data_dir, "search", "--type", "expense", "--category", "parts")
        narrow_elapsed, _ = run_cli_timed(data_dir, "search", "--q", "강좌")
        rss_after = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        peak_bytes = max(child_rss_bytes(rss_before), child_rss_bytes(rss_after))
        print(f"list --limit 5            : {list_elapsed * 1000:.1f}ms")
        print(f"search --category parts   : {search_elapsed * 1000:.1f}ms (전체 역순 스캔)")
        print(f"search --q 강좌            : {narrow_elapsed * 1000:.1f}ms")
        print(f"자식 프로세스 최대 RSS      : {peak_bytes / 1024 / 1024:.1f}MiB")

        repo = TransactionRepository(data_dir)
        started = time.perf_counter()
        count = sum(1 for _ in repo.iter_all())
        full_parse = time.perf_counter() - started
        started = time.perf_counter()
        top5 = list(repo.iter_newest_first(5))
        bounded_read = time.perf_counter() - started
        print(f"프로세스 내 전체 파싱 {count:,}건 : {full_parse:.2f}초")
        print(f"프로세스 내 역순 5건        : {bounded_read * 1000:.2f}ms (블록+5건 메모리)")
        print(f"샘플 최신순 id: {top5[0].id} … {top5[-1].id}")
        return 0
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
