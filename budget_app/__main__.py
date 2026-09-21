"""`python -m budget_app` 진입점.

골격 단계: 서브커맨드 등록 전의 빈 파서. add/list/search/summary/budget/
category/update/delete/import/export 명령 연결과 계층(CLI/서비스/저장소/모델)
구현은 다음 단계에서 작성한다.
"""

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="budget_app",
        description="파일 기반 용돈 기입장 콘솔 앱",
    )
    parser.parse_args()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
