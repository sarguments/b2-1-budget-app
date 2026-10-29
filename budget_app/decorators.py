"""로그·시간 측정·예외 변환 decorator(공통 처리 모듈).

세 개의 decorator를 `functools.wraps`로 제공하고 서비스 메서드에 겹쳐
적용한다: `@handle_errors`(가장 바깥쪽, OSError→StorageError 변환) →
`@timed`(소요 시간) → `@logged`(호출 기록).

출력은 전부 stderr(로거)로 보낸다. stdout은 명령 결과 전용이라
`--verbose`를 켜면 DEBUG 로그가 stderr에 드러나고, 꺼 두면 CRITICAL
로그 레벨로 DEBUG 출력을 숨긴다.
"""

from __future__ import annotations

import functools
import logging
import sys
import time
from typing import Callable, Final, ParamSpec, TypeVar

from budget_app.errors import AppError, StorageError

P = ParamSpec("P")
R = TypeVar("R")

#: 패키지 공용 로거. cli.configure_logging()이 핸들러·레벨을 결정한다.
LOGGER: Final[logging.Logger] = logging.getLogger("budget_app")


def configure_logging(verbose: bool) -> None:
    """--verbose 여부로 decorator 로그 노출을 켜고 끈다(stderr 전용)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[로그] %(levelname)s %(message)s"))
    LOGGER.handlers = [handler]
    LOGGER.setLevel(logging.DEBUG if verbose else logging.CRITICAL)
    LOGGER.propagate = False


def logged(func: Callable[P, R]) -> Callable[P, R]:
    """호출 시작·완료 기록을 DEBUG로 남긴다."""

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        LOGGER.debug("시작 %s", func.__qualname__)
        result = func(*args, **kwargs)
        LOGGER.debug("완료 %s", func.__qualname__)
        return result

    return wrapper


def timed(func: Callable[P, R]) -> Callable[P, R]:
    """메서드 실행 소요 시간을 DEBUG로 남긴다(밀리초, 소수점 둘째 자리까지).

    generator 함수에 적용하면 iterator를 만드는 시간만 측정한다.
    따라서 이 앱에서는 iter_* 메서드에 적용하지 않는다.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        started = time.perf_counter()
        result = func(*args, **kwargs)
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        LOGGER.debug("소요 %s: %.2fms", func.__qualname__, elapsed_ms)
        return result

    return wrapper


def handle_errors(func: Callable[P, R]) -> Callable[P, R]:
    """예상 오류는 그대로 올리되, 파일 시스템 오류를 사용자 메시지로 변환.

    OSError(없는 파일·권한 부족 등)를 그대로 두면 traceback이 뜨므로
    [오류]/[힌트]를 담당한 StorageError로 감싼다. AppError와 그 하위 예외는
    이미 사용자 문구를 갖고 있어 통과시키고, 기록만 남긴다.
    """

    @functools.wraps(func)
    def wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
        try:
            return func(*args, **kwargs)
        except AppError as err:
            LOGGER.debug("예상 오류 %s: %s", func.__qualname__, err.cause)
            raise
        except OSError as exc:
            reason = exc.strerror or str(exc)
            raise StorageError(
                f"파일 처리에 실패했습니다: {reason}",
                "데이터 디렉터리(--data-dir) 경로와 권한을 확인하세요.",
            ) from exc

    return wrapper


__all__ = ["LOGGER", "configure_logging", "handle_errors", "logged", "timed"]
