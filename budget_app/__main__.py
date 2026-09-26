"""`python -m budget_app` 진입점.

실제 동작은 cli.main()에 위임하고, 여기서는 종료 코드만 SystemExit으로
전달한다. 계층(CLI/서비스/저장소/모델) 구조는 README 참조.
"""

from budget_app.cli import main as cli_main


def main() -> int:
    return cli_main()


if __name__ == "__main__":
    raise SystemExit(main())
