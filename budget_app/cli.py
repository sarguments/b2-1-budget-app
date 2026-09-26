"""CLI 계층: 인수를 해석하고 서비스를 호출하며 stdout에 결과를 찍는다.

여기서 출력하는 것은 명령 결과뿐이다. 오류도 [오류]/[힌트] 두 줄 문구로
stdout에 내보내고 스택 트레이스는 절대 보여주지 않는다.
종료 코드는 errors.py의 약속(성공 0 / 도메인 1 / 사용법 2)을 따른다.
"""

from __future__ import annotations

import argparse
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import NoReturn, TypeVar

from budget_app import formatting
from budget_app.decorators import LOGGER, configure_logging
from budget_app.errors import AppError, StorageError, UsageError, ValidationError
from budget_app.models import NewTransaction, TransactionPatch
from budget_app.parsing import (
    parse_amount,
    parse_date,
    parse_month,
    parse_tags,
    parse_type,
    validate_category_name,
)
from budget_app.service import BudgetService, SearchCriteria

T = TypeVar("T")

#: 이 명령들을 실행할 때 카테고리 파일이 비어 있으면 기본값을 채운다(안 A).
_SEED_COMMANDS = frozenset({"add", "category", "import", "update"})


class _AppParser(argparse.ArgumentParser):
    """argparse 실패도 [오류]/[힌트]·종료 코드 2로 바꾸는 파서."""

    def error(self, message: str) -> NoReturn:
        raise UsageError(
            f"명령 인수가 잘못됐습니다: {message}",
            "budget_app <명령> --help 로 정확한 사용법을 확인하세요.",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = _AppParser(
        prog="budget_app",
        description="파일 기반 용돈 기입장 콘솔 앱 (로봇 학습 지출 기록)",
    )
    parser.add_argument(
        "--data-dir", default="./data", metavar="DIR",
        help="데이터 저장 디렉터리 (기본 ./data)",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="데코레이터의 로그·소요 시간을 stderr에 출력",
    )
    sub = parser.add_subparsers(dest="command", required=True, metavar="<명령>")

    sub.add_parser("add", help="거래를 대화형으로 입력받아 추가")

    p_list = sub.add_parser("list", help="최근 추가순으로 거래 목록 출력")
    p_list.add_argument("--limit", type=int, default=20, metavar="N", help="출력 건수 (기본 20)")

    p_search = sub.add_parser("search", help="조건(AND)으로 거래를 찾아 최신순 출력")
    p_search.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="시작일(포함)")
    p_search.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="끝일(포함)")
    p_search.add_argument("--category", default="", metavar="NAME", help="카테고리 일치")
    p_search.add_argument("--type", default="", choices=["", "income", "expense"], metavar="TYPE", help="income|expense")
    p_search.add_argument("--q", dest="query", default="", metavar="KEYWORD", help="메모 부분일치(대소문자 무시)")
    p_search.add_argument("--tag", default="", metavar="TAG", help="태그 일치(대소문자 무시)")

    p_summary = sub.add_parser("summary", help="월별 수입/지출/잔액·예산 사용률·지출 TOP")
    p_summary.add_argument("--month", required=True, metavar="YYYY-MM", help="집계할 월")
    p_summary.add_argument("--top", type=int, default=3, metavar="N", help="지출 TOP 개수 (기본 3)")

    p_budget = sub.add_parser("budget", help="월 예산 설정/목록")
    budget_sub = p_budget.add_subparsers(dest="budget_command", required=True, metavar="<하위>")
    p_budget_set = budget_sub.add_parser("set", help="월 예산 등록/수정")
    p_budget_set.add_argument("--month", required=True, metavar="YYYY-MM", help="대상 월")
    p_budget_set.add_argument("--amount", required=True, type=int, metavar="N", help="예산 금액(양수)")
    budget_sub.add_parser("list", help="등록된 월 예산 목록")

    p_category = sub.add_parser("category", help="카테고리 추가/목록/삭제")
    category_sub = p_category.add_subparsers(dest="category_command", required=True, metavar="<하위>")
    p_category_add = category_sub.add_parser("add", help="카테고리 추가(이름 생략 시 대화형)")
    p_category_add.add_argument("name", nargs="?", metavar="NAME", help="카테고리 이름")
    category_sub.add_parser("list", help="카테고리 목록")
    p_category_remove = category_sub.add_parser("remove", help="사용 중인 거래가 있으면 차단")
    p_category_remove.add_argument("name", nargs="?", metavar="NAME", help="카테고리 이름")

    p_update = sub.add_parser("update", help="id로 거래를 찾아 주어진 옵션만 수정")
    p_update.add_argument("--id", dest="tx_id", default="", metavar="TX-000001", help="대상 거래 id")
    p_update.add_argument("--date", metavar="YYYY-MM-DD", help="바꿀 날짜")
    p_update.add_argument("--type", choices=["income", "expense"], metavar="TYPE", help="바꿀 타입")
    p_update.add_argument("--category", metavar="NAME", help="바꿀 카테고리(등록된 것만)")
    p_update.add_argument("--amount", type=int, metavar="N", help="바꿀 금액(양수)")
    p_update.add_argument("--memo", metavar="TEXT", help="바꿀 메모(빈 문자열로 초기화)")
    p_update.add_argument("--tags", metavar="T1,T2", help="바꿀 태그(쉼표 구분, 전체 교체)")

    p_delete = sub.add_parser("delete", help="id로 거래 삭제")
    p_delete.add_argument("--id", dest="tx_id", default="", metavar="TX-000001", help="대상 거래 id")

    p_import = sub.add_parser("import", help="CSV를 읽어 거래로 추가(유효 행만, 부분 성공)")
    p_import.add_argument("--from", dest="source", required=True, metavar="CSV", help="읽을 CSV 경로")

    p_export = sub.add_parser("export", help="조건에 맞는 거래를 CSV로 내보내기")
    p_export.add_argument("--out", required=True, metavar="CSV", help="내보낼 CSV 경로")
    p_export.add_argument("--month", metavar="YYYY-MM", help="월 조건")
    p_export.add_argument("--from", dest="date_from", metavar="YYYY-MM-DD", help="시작일(포함)")
    p_export.add_argument("--to", dest="date_to", metavar="YYYY-MM-DD", help="끝일(포함)")

    return parser


# ---- 대화형 add ----------------------------------------------------------


def _prompt(prompt: str, parse: Callable[[str], T]) -> T:
    """한 필드를 유효값이 나올 때까지 반복 입력받는다. 입력 고갈은 오류 1건."""
    while True:
        try:
            raw = input(prompt)
        except (EOFError, KeyboardInterrupt):
            raise ValidationError(
                "입력이 끝나 거래 추가를 중단했습니다.",
                "다시 실행하거나, 파이프 입력이라면 필드 순서대로 값을 보내세요.",
            )
        try:
            return parse(raw)
        except ValidationError as err:
            _print_error(err)


def _prompt_category(service: BudgetService) -> Callable[[str], str]:
    def parse(raw: str) -> str:
        name = raw.strip()
        if not name:
            raise ValidationError("카테고리는 빈 값일 수 없습니다.", "food, edu 등 이름을 입력하세요.")
        if not service.has_category(name):
            raise ValidationError(
                f"'{name}'는 등록된 카테고리가 아닙니다.",
                "category add로 먼저 등록하거나 category list에서 이름을 확인하세요.",
            )
        return name

    return parse


def cmd_add(service: BudgetService) -> None:
    date = _prompt("날짜(YYYY-MM-DD): ", parse_date)
    tx_type = _prompt("타입(income/expense): ", parse_type)
    category = _prompt("카테고리: ", _prompt_category(service))
    amount = _prompt("금액(양수): ", parse_amount)
    memo = _prompt("메모(선택): ", lambda raw: raw.strip())
    tags = _prompt("태그(쉼표로 구분, 없으면 엔터): ", parse_tags)
    draft = NewTransaction(type=tx_type, date=date, amount=amount, category=category, memo=memo, tags=tags)
    tx = service.add_transaction(draft)
    print(f"[저장 완료] id={tx.id}")


# ---- 조회·집계 -------------------------------------------------------------


def cmd_list(service: BudgetService, limit: int) -> None:
    if limit < 1:
        raise UsageError(f"--limit은 1 이상이어야 합니다: {limit}", "예: list --limit 10")
    printed = False
    for tx in service.iter_newest_first(limit):
        print(formatting.transaction_row(tx))
        printed = True
    if not printed:
        print("(거래가 없습니다. add로 추가하세요.)")


def _search_criteria(args: argparse.Namespace) -> SearchCriteria:
    month_raw = getattr(args, "month", "")
    criteria = SearchCriteria(
        month=parse_month(month_raw) if month_raw else "",
        date_from=parse_date(args.date_from) if args.date_from else "",
        date_to=parse_date(args.date_to) if args.date_to else "",
        tx_type=getattr(args, "type", "") or "",
        category=getattr(args, "category", "") or "",
        query=getattr(args, "query", "") or "",
        tag=getattr(args, "tag", "") or "",
    )
    if criteria.date_from and criteria.date_to and criteria.date_from > criteria.date_to:
        raise ValidationError(
            f"범위가 역방향입니다({criteria.date_from} > {criteria.date_to}).",
            "--from을 --to보다 앞(이른) 날짜로 지정하세요.",
        )
    return criteria


def cmd_search(service: BudgetService, criteria: SearchCriteria) -> None:
    printed = False
    for tx in service.iter_matching(criteria):
        print(formatting.transaction_row(tx))
        printed = True
    if not printed:
        print("(조건에 맞는 거래가 없습니다.)")


def cmd_summary(service: BudgetService, month_raw: str, top: int) -> None:
    if top < 1:
        raise UsageError(f"--top은 1 이상이어야 합니다: {top}", "예: summary --month 2024-01 --top 5")
    result = service.summarize(parse_month(month_raw), top)
    for row in formatting.summary_rows(
        result.month, result.income, result.expense, result.budget, result.top_expense
    ):
        print(row)


# ---- 예산·카테고리 ----------------------------------------------------------


def cmd_budget_set(service: BudgetService, month_raw: str, amount: int) -> None:
    month = parse_month(month_raw)
    budget = service.set_budget(month, parse_amount(amount))
    print(f"[저장 완료] {budget.month} 예산 {budget.amount}원")


def cmd_budget_list(service: BudgetService) -> None:
    budgets = service.list_budgets()
    if not budgets:
        print("(등록된 예산이 없습니다. budget set --month YYYY-MM --amount N)")
        return
    for budget in budgets:
        print(formatting.budget_row(budget))


def _obtain_category_name(name: str | None) -> str:
    """category add/remove의 이름 인수. 생략되면 대화형으로 받는다."""
    if name is not None and name.strip():
        return name.strip()
    return _prompt("카테고리: ", _parse_non_empty_name)


def _parse_non_empty_name(raw: str) -> str:
    value = raw.strip()
    if not value:
        raise ValidationError("카테고리 이름은 비울 수 없습니다.", "food, edu 같은 이름을 입력하세요.")
    return value


def cmd_category(service: BudgetService, action: str, name: str | None) -> None:
    match action:
        case "list":
            categories = service.list_categories()
            if not categories:
                print("(카테고리가 없습니다.)")
                return
            for category in categories:
                print(formatting.category_row(category))
            return
        case "add":
            category = service.add_category(_obtain_category_name(name))
            print(f"[저장 완료] 카테고리 '{category.name}'")
            return
        case "remove":
            category = service.remove_category(_obtain_category_name(name))
            print(f"[삭제 완료] 카테고리 '{category.name}'")
            return
        case _:
            raise UsageError(f"지원하지 않는 category 하위 명령: {action}", "add/list/remove만 지원합니다.")


# ---- 거래 수정·삭제 ----------------------------------------------------------


def _require_tx_id(tx_id: str) -> str:
    value = tx_id.strip()
    if not value:
        raise ValidationError(
            "거래 id가 지정되지 않았습니다.",
            "--id TX-000001 형태로 지정하세요. list로 id를 찾을 수 있습니다.",
        )
    return value


def cmd_update(service: BudgetService, args: argparse.Namespace) -> None:
    tx_id = _require_tx_id(args.tx_id)
    patch = TransactionPatch(
        date=parse_date(args.date) if args.date is not None else None,
        type=parse_type(args.type) if args.type is not None else None,
        category=validate_category_name(args.category) if args.category is not None else None,
        amount=parse_amount(args.amount) if args.amount is not None else None,
        memo=args.memo.strip() if args.memo is not None else None,
        tags=parse_tags(args.tags) if args.tags is not None else None,
    )
    if not patch.has_changes():
        raise UsageError(
            "변경할 필드가 없습니다.",
            "--date/--type/--category/--amount/--memo/--tags 중 하나 이상을 지정하세요.",
        )
    updated = service.update_transaction(tx_id, patch)
    print(f"[수정 완료] id={updated.id}")
    print(formatting.transaction_row(updated))


def cmd_delete(service: BudgetService, tx_id: str) -> None:
    removed = service.delete_transaction(_require_tx_id(tx_id))
    print(f"[삭제 완료] id={removed.id}")


# ---- import/export ---------------------------------------------------------


def cmd_import(service: BudgetService, source: str) -> None:
    result = service.import_csv(Path(source))
    print(f"[완료] imported={result.imported}, skipped={len(result.skipped)}")
    for reason in result.skipped:
        print(f"  {reason}")
    if result.imported == 0 and result.skipped:
        raise ValidationError(
            f"유효한 행이 하나도 없어 저장된 거래가 없습니다(건너뜀 {len(result.skipped)}건).",
            "위 사유(형식 오류·미등록 카테고리)를 고친 뒤 다시 시도하세요. "
            "이미 import한 행은 중복 제거되지 않으므로 파일 전체를 무작정 다시 실행하지 마세요.",
        )


def cmd_export(service: BudgetService, args: argparse.Namespace) -> None:
    if not (args.month or args.date_from or args.date_to):
        raise UsageError(
            "export 조건이 없습니다.",
            "--month YYYY-MM 또는 --from/--to 중 하나 이상을 지정하세요.",
        )
    criteria = _search_criteria(args)
    count = service.export_csv(Path(args.out), criteria)
    print(f"[완료] {args.out} ({count} records)")


# ---- 진입점 -----------------------------------------------------------------


def _print_error(err: AppError) -> None:
    print(f"[오류] {err.cause}")
    print(f"[힌트] {err.hint}")


def _dispatch(args: argparse.Namespace, service: BudgetService) -> int:
    command = args.command
    if command in _SEED_COMMANDS:
        service.ensure_default_categories()
    match command:
        case "add":
            cmd_add(service)
        case "list":
            cmd_list(service, args.limit)
        case "search":
            cmd_search(service, _search_criteria(args))
        case "summary":
            cmd_summary(service, args.month, args.top)
        case "budget":
            match args.budget_command:
                case "set":
                    cmd_budget_set(service, args.month, args.amount)
                case "list":
                    cmd_budget_list(service)
                case _:
                    raise UsageError(
                        f"지원하지 않는 budget 하위 명령: {args.budget_command}",
                        "set/list만 지원합니다.",
                    )
        case "category":
            cmd_category(service, args.category_command, getattr(args, "name", None))
        case "update":
            cmd_update(service, args)
        case "delete":
            cmd_delete(service, args.tx_id)
        case "import":
            cmd_import(service, args.source)
        case "export":
            cmd_export(service, args)
        case _:
            raise UsageError(f"지원하지 않는 명령: {command}", "--help로 지원 명령을 확인하세요.")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    """`python -m budget_app`의 실제 진입점. 종료 코드를 돌려준다.

    parse_args 중의 인수 오류(_AppParser.error가 던지는 UsageError)도
    잡아야 하므로 파싱부터 try 안에 둔다. --help의 SystemExit(0)은
    BaseException이라 그대로 통과해 정상 종료한다.
    """
    try:
        args = build_parser().parse_args(argv)
        configure_logging(args.verbose)
        return _dispatch(args, BudgetService(Path(args.data_dir)))
    except AppError as err:
        _print_error(err)
        return err.exit_code
    except KeyboardInterrupt:
        _print_error(ValidationError("입력 중단으로 작업을 취소했습니다.", "같은 명령을 다시 실행하세요."))
        return 1
    except OSError as exc:  # 데코레이터를 거치지 않은 경로(생성기 등)의 파일/권한 오류도 트레이스 없이 안내한다.
        _print_error(
            StorageError(
                f"파일 처리에 실패했습니다: {exc.strerror or exc}",
                "데이터 디렉터리(--data-dir) 경로와 권한을 확인하세요.",
            )
        )
        return 1
    except Exception as exc:  # 최외곽 안전망: 예측 못 한 오류도 트레이스 없이 안내한다.
        LOGGER.error("예상치 못한 내부 오류: %s", exc)
        _print_error(
            ValidationError(
                f"예상치 못한 내부 오류가 발생했습니다({type(exc).__name__}).",
                "--verbose로 재실행해 stderr 로그를 남기고 재현되면 유지보수자에게 제보하세요.",
            )
        )
        return 1


__all__ = ["build_parser", "main"]
