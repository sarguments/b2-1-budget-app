# REFERENCE — B2-1 용돈 기입장 참고 구현 (제출용 아님)

> **이 브랜치(`ref/b2-1-solution`)는 참고용 모범 답안이다. 과제 제출에 사용하지 말 것.**
> 채점용 제출은 제출 브랜치에서 **본인이 직접** 작성한 구현이어야 한다. 이 문서는
> "요구사항이 코드·문서에서 어디 어떻게 충족되는지" 짚어 주는 지도이고, README의
> 근거 설명을 읽은 뒤 자기 구현과 **비교**하는 교재로 쓴다. 복사해서 제출하면
> 미션 취지(직접 수행·이해·재현)에 어긋난다.

## 이 참고 구현의 위치

- 코드: `budget_app/`(11개 모듈) + `tests/`(99개 unittest) + `scripts/bench_100k.py`
- 설명: `README.md`(실행 방법·저장 형식·모듈 책임·JSONL vs CSV·병목 분석·원자 교체·종료 코드 표)
- 검증 근거: 2026-09-26 로컬(Python 3.14.3, `.venv`)에서 아래 명령으로 실행 확인
  - `.venv/bin/python -m unittest discover -s tests -v` → 99 tests OK
  - 독립 리뷰 지적 반영(2차): export가 데이터 파일을 덮어쓰지 못하게 차단, import를 `os.replace` 원자 저장으로 변경, 전 행 무효 import는 종료 1, `--verbose`에서도 traceback 미출력(OSError를 원인+힌트로 변환), CSV 고정 스키마 검증(중복·미지 열 거부), 거래 없는 달의 예산 표시, `meta.json` 소실 시 기존 id에서 채번 복구
  - `.venv/bin/python scripts/bench_100k.py` → 10만 건 list/search 실측
  - README 「주요 명령 예시」의 모든 출력과 종료 코드는 실제 실행 결과

## 사용 방법(권장 순서)

1. `python -m budget_app --help`로 10개 명령의 윤곽을 잡고, README 「실행 방법」을 읽는다.
2. 미션 원문의 요구를 하나씩 자기 구현에 반영한 뒤, 같은 요구가 이 참고 구현에서
   **어느 파일·어느 함수**에서 어떻게 풀렸는지 아래 표와 견준다.
3. 표에 없는 자기만의 판단(문구·파일명·기본값)은 그대로 두고, 표에서 **이해가 안 되는
   항목만** README 상세 절로 들어가 읽는다.
4. 최종 제출 전에 이 저장소 코드를 커밋·복사하지 않았는지 `git status`로 확인한다.

## AI 채점 16개 항목 ↔ 구현/문서 대응표

| # | 채점 항목 | 코드 근거 | 문서/검증 근거 |
|---|---|---|---|
| 1 | 모든 서브커맨드 구현 + 단위 실행 증거 | `cli.py` 10개 cmd_*, `service.py` | README 「주요 명령 예시」, `tests/test_cli.py`(서브커맨드별 `--help` 포함) |
| 2 | 저장 파일 3개 이상 + 재시작 후 지속 | `repositories.py` 3저장소 + `storage.py` `SequenceFile`(meta.json 포함 4개) | README 「저장 파일 위치·형식」, `test_cli.py::test_list_row_format_and_persistence_across_processes`(프로세스 분리) |
| 3 | 카테고리 add/list/remove + 사용 중 삭제 정책 | `CategoryRepository.add/remove`, `BudgetService.remove_category`(in-use 차단) | README 오류 예시, `test_cli.py::CategoryPolicyTest` |
| 4 | budget set 저장 + summary 사용률·초과 경고 | `BudgetRepository.upsert`, `formatting.summary_rows` | README summary 예시(사용률·[경고] 줄), `test_cli.py::test_summary_shows_budget_usage_and_top` |
| 5 | CSV 헤더/인코딩 + 고정 스키마 + 테스트 파일 생성 | `models.CSV_HEADER`, `service.import_csv/export_csv`(utf-8) | README 스키마 표, `test_cli.py::test_export_writes_schema_header_then_import_roundtrip` |
| 6 | 오류 출력(트레이스 없음, 원인+힌트) | `errors.py` cause/hint, `cli.main` 최외곽 catch, `_print_error` | README 「오류 처리와 종료 코드」, 모든 CLI 테스트가 `Traceback` 부재를 함께 단언 |
| 7 | 오류 시 비0 종료 + 테스트 스크립트 | `AppError.exit_code`(1/2), `cli.main` 반환 | `tests/` 전체, 검증 리포트의 `exit=1`/`exit=2` 출력 |
| 8 | 모듈 3개 이상 분리 + 책임 문서화 | `budget_app/` 11모듈(parsing=models 분리로 검증 규칙과 값 객체를 분리) | README 「모듈 구조와 책임」 표 |
| 9 | 클래스 2개 이상 + 역할/인스턴스 책임 | `Transaction/Category/Budget`(모델), 3 Repository, `BudgetService`, `JsonlStore/SequenceFile` | README 「클래스별 역할」 |
| 10 | 임시 파일 원자 교체 + 롤백 | `storage.JsonlStore.replace_stream`(temp+fsync+os.replace, 실패 시 temp 삭제) | README 「원자적 교체 전략」, `test_storage.py::test_replace_stream_failure_keeps_original_and_removes_temp` |
| 11 | 생성자 스트리밍(list/search, 메모리 절약) | `storage.iter_lines_reversed`(역순 블록 읽기), `repositories.iter_newest_first` | README 「10만 건 실측」(list가 파일 크기와 무관한 밀리초), `test_storage.py::IterLinesReversedTest` |
| 12 | 로그/시간/예외 데코레이터 별도 모듈 + 사용 | `decorators.py` `logged/timed/handle_errors`, `service.py` 메서드 적용 | README 「데코레이터 사용 예」, `test_cli.py::test_verbose_writes_decorator_logs_to_stderr_only` |
| 13 | 타입 힌트 전반 + 설명 | 모든 함수·dataclass 필드 시그니처, `Literal`, frozen slots (`parsing.py`가 형식 규칙, `models.py`가 값 객체) | README 「타입 힌트 정책」 |
| 14 | JSONL vs CSV 비교 + 선택 근거 | `storage.py`(JSONL 선택 구현) | README 「JSONL vs CSV」 비교 표 |
| 15 | 10만 건 병목 후보 + 개선안 | `scripts/bench_100k.py` 실측 | README 「병목 후보와 개선안」(파싱/스캔/디스크 I/O와 수치) |
| 16 | 부분 import 실패 정책(롤백/보고/유도) | `service.import_csv`(전 줄 사전검증 → 유효분만 단일 append, skip 사유 목록) | README 「import 부분 성공」, `test_cli.py::test_partial_import_stores_valid_skips_invalid` |

## 자기 구현과 비교할 때 볼 핵심 판단 포인트

- **id 채번**: 삭제 후 재추가 시 id가 재사용되지 않게 `meta.json` 별도 카운터로
  단조 증가를 보장(`SequenceFile.advance` 순서: peek→확정 쓰기→거래 append).
- **list 최신순**: 파일 앞에서 읽으면 O(n)이라 **역순 블록 읽기**로 최근 건만 건드린다.
- **update/delete 원자성**: 전체 재작성을 temp 파일로 만들고 `os.replace`(POSIX
  원자적 rename)로만 확정. 실패 시 temp 삭제 = 원본 무변경.
- **search/export 필터**: `SearchCriteria.matches` 한 곳에서 AND 결합 — 조건 추가 시
  조합 Explosion 없이 확장.
- **대화형 add 재입력**: 필드별 파서를 `_prompt(parse)`에 주입해 같은 루프를 6개
  필드에서 공유(중복 없는 retry).
