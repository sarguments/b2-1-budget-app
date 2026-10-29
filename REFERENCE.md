# 참고 구현 읽기 안내

`ref/b2-1-solution`은 구조와 동작을 비교하기 위한 참고 브랜치입니다.
실행 방법과 저장 정책은 [README.md](README.md)를 참고하세요.

## 읽는 순서

1. `budget_app/cli.py`의 `build_parser`와 `_dispatch`에서 명령이 연결되는 흐름을 봅니다.
2. `service.py`에서 명령별 규칙을 확인합니다.
3. `repositories.py`와 `storage.py`에서 데이터가 파일에 저장되는 과정을 봅니다.
4. `models.py`와 `parsing.py`에서 입력과 저장 데이터를 검증하는 규칙을 확인합니다.
5. `tests/`에서 정상 입력과 오류 입력의 예상 결과를 확인합니다.

## 기능별 코드와 테스트

| 기능 | 코드 | 확인할 테스트 |
|---|---|---|
| 명령과 도움말 | `cli.build_parser`, `cli._dispatch` | `test_cli.HelpAndSeedTest` |
| 거래 추가와 저장 유지 | `BudgetService.add_transaction`, `TransactionRepository.add` | `test_cli.AddListPersistenceTest` |
| 카테고리 관리 | `CategoryRepository`, `BudgetService.remove_category` | `test_cli.CategoryPolicyTest` |
| 검색과 월별 집계 | `SearchCriteria.matches`, `BudgetService.summarize` | `test_cli.SearchSummaryBudgetTest` |
| 거래 수정·삭제 | `TransactionRepository._rewrite` | `test_cli.UpdateDeleteTest`, `test_storage.TransactionRepositoryTest` |
| CSV import/export | `BudgetService.import_csv`, `BudgetService.export_csv` | `test_cli.ImportExportTest` |
| 날짜·ID 순서, top N 선택과 streaming | `TransactionRepository.iter_newest_first`, `_merge_runs` | `test_storage.TransactionRepositoryTest` |
| 초기 저장 파일 생성 | `BudgetService.__init__` | `test_cli.HelpAndSeedTest` |
| 파일 교체와 실패 처리 | `JsonlStore.replace_stream` | `test_storage.JsonlStoreTest` |
| 거래 번호 | `SequenceFile`, `TransactionRepository` | `test_storage.SequenceFileTest`, `test_storage.TransactionRepositoryTest` |
| 모델과 parsing | `models.py`, `parsing.py` | `test_models.py` |
| 로그·시간 측정·오류 변환 | `decorators.py`, `cli.main` | `test_cli`의 verbose·파일 오류 테스트 |
| 성능 측정 | `scripts/bench_100k.py` | `test_bench_units.py` |

## 비교할 설계 선택

- **거래일순 목록**: 날짜가 최신인 순서로, 같은 날짜에서는 ID의 숫자가 큰 순서로 출력합니다. 과거 날짜의 추가·날짜 수정 후에도 순서가 유지되는지 확인하세요.
- **Top N 선택**: list의 limit이 1,024 이하이면 generator로 전체 파일을 읽고 `heapq.nlargest`로 상위 N건만 메모리에 유지합니다. 임시 정렬 파일을 만들지 않는지 확인하세요.
- **External merge sort**: 큰 limit이나 무제한 조회는 1,024건씩 정렬한 임시 JSONL을 최대 32개씩 merge합니다. search/export는 조건에 맞는 거래만 정렬합니다. 입력 파일은 모두 읽지만 메모리에는 전체 거래를 모으지 않습니다. 정렬 완료·generator 종료·오류 시 임시 파일이 정리되는지도 확인하세요.
- **초기 파일 생성**: 처음 실행하면 3개의 JSONL 저장 파일을 만들고 기존 파일은 보존합니다.
- **거래 번호 저장**: 거래를 삭제해도 다음 번호를 따로 보관합니다. ID는 최소 6자리이며 1000000 이후에도 늘어납니다. 번호 파일이 없거나 잘못된 경우도 확인하세요.
- **빈 달 요약**: 거래가 없는 달에 예산만 등록돼 있으면 거래 없음 안내와 예산 사용률을 함께 표시합니다.
- **파일 교체**: 수정·삭제·import 중 쓰기가 실패했을 때 기존 거래 파일이 유지되는지 확인합니다.
- **검색 조건**: `SearchCriteria.matches`에서 모든 조건을 AND로 결합합니다.
- **입력 재시도**: `_prompt`에 필드별 parsing 함수를 전달해 재입력 흐름을 공유합니다.
- **Generator 측정**: iterator를 만드는 시간과 실제로 순회하는 시간을 구분합니다.
- **Import 부분 성공**: 유효한 행만 저장하고, 건너뛴 행의 이유를 출력합니다. 같은 CSV를 다시 가져오면 중복 거래가 생긴다는 점도 확인하세요.

## 실행 확인

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/bench_100k.py
```

테스트는 정상·오류 입력과 저장 동작을 확인합니다. 성능 측정은 거래 10만 건으로 현재 환경의 목록·검색 실행 시간과 메모리 사용량을 출력합니다.
