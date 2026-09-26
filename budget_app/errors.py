"""응용 오류 타입들.

이 앱의 모든 예상 오류는 `AppError` 계통이며 `원인(cause)`·`힌트(hint)`·
`종료 코드(exit_code)`를 데이터로 담는다. CLI 최상단에서만 메시지 형태로
변환해 출력하므로 스택 트레이스는 사용자에게 보이지 않는다.

종료 코드 규약:
- 1: 도메인/데이터 오류(입력 검증, 없음, 충돌, 파일 문제)
- 2: 사용법/인수 오류(명령 형식, 필수 옵션 누락)
"""

from __future__ import annotations

DOMAIN_EXIT_CODE: int = 1
USAGE_EXIT_CODE: int = 2


class AppError(Exception):
    """사용자에게 [오류]/[힌트]로 보여 주는 기본 예외."""

    exit_code: int = DOMAIN_EXIT_CODE

    def __init__(self, cause: str, hint: str) -> None:
        super().__init__(cause)
        self.cause = cause
        self.hint = hint


class ValidationError(AppError):
    """입력값이나 저장 데이터가 요구 형식에 맞지 않는다."""


class NotFoundError(AppError):
    """대상 id/레코드가 저장소에 없다."""


class ConflictError(AppError):
    """업무 규칙과 충돌한다(중복 카테고리, 사용 중인 카테고리 삭제 등)."""


class StorageError(AppError):
    """파일 읽기/쓰기 자체가 실패했다(경로·권한·디스크 문제)."""


class UsageError(AppError):
    """명령 형식 오류. argparse 실패와 같은 단계이며 종료 코드 2를 쓴다."""

    exit_code: int = USAGE_EXIT_CODE
