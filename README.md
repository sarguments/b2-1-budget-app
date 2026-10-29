# b2-1-budget-app

Python 3.10 이상에서 실행하는 파일 기반 용돈 기입장입니다. 표준 라이브러리만 사용합니다.

거래 추가·목록·검색·수정·삭제, 월별 요약, 예산과 카테고리 관리, CSV import/export를 지원합니다.
로봇 부품·장비·교육·교통비 등 개인 지출을 기록하는 용도로 구성했습니다.
이 구현은 `ref/b2-1-solution` 브랜치에 있습니다. `main`은 학습용 골격입니다.

## 실행 준비

```bash
git clone https://github.com/sarguments/b2-1-budget-app.git
cd b2-1-budget-app
git switch ref/b2-1-solution
```

Python 버전이 3.10 이상인지 확인한 뒤 가상환경을 만듭니다. 기본 `python3`의 버전이 낮으면 설치된 상위 버전의 실행 파일을 지정합니다.

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python -m budget_app --help
```

외부 패키지 설치는 필요하지 않습니다.

## 명령 사용법

저장소 루트에서 실행합니다.

```bash
.venv/bin/python -m budget_app add
.venv/bin/python -m budget_app list --limit 20
.venv/bin/python -m budget_app search --from 2026-10-01 --to 2026-10-31 --type expense
.venv/bin/python -m budget_app summary --month 2026-10 --top 3
.venv/bin/python -m budget_app budget set --month 2026-10 --amount 500000
.venv/bin/python -m budget_app budget list
.venv/bin/python -m budget_app category add robot-kit
.venv/bin/python -m budget_app category list
.venv/bin/python -m budget_app category remove robot-kit
.venv/bin/python -m budget_app update --id TX-000001 --memo 도시락 --tags lunch,work
.venv/bin/python -m budget_app delete --id TX-000001
.venv/bin/python -m budget_app export --out backup.csv --month 2026-10
.venv/bin/python -m budget_app import --from backup.csv
```

각 줄은 별도의 사용 예시입니다. 조회·수정·삭제에는 해당 데이터가 먼저 있어야 합니다.
모든 명령과 하위 명령에서 `--help`로 옵션을 확인할 수 있습니다.
옵션은 리눅스 long option 형식인 `--limit`, `--month`처럼 `--`를 사용합니다.

전역 옵션은 명령 앞에 붙입니다.

```bash
.venv/bin/python -m budget_app --data-dir /tmp/budget-demo --verbose category list
```

- `--data-dir DIR`: 저장 폴더. 기본값은 현재 작업 폴더의 `./data`입니다.
- `--verbose`: decorator의 로그와 실행 시간을 stderr에 출력합니다.
- `list`와 `search`는 **거래일 내림차순**으로 출력합니다. 날짜가 같으면 거래 ID의 숫자 부분이 큰 순서로 출력합니다. 과거 날짜를 나중에 입력해도 거래일 순서가 유지됩니다.
- `summary`는 거래가 없는 달을 안내합니다. 예산만 등록된 달은 거래가 없다는 안내와 예산 사용률 0.0%를 함께 출력합니다.
- `update`는 옵션으로 지정한 필드만 변경합니다. `--memo ''`, `--tags ''`로 값을 비울 수 있습니다.

## 거래 입력과 카테고리

`add`는 날짜, 타입, 카테고리, 금액, 메모, 태그를 차례로 입력받습니다.
날짜·타입·카테고리·금액의 기본값은 각 프롬프트에 표시됩니다. 잘못된 필드 값은 오류와 힌트를 출력한 뒤 다시 입력받습니다.

카테고리 파일이 없거나 비어 있으면 `add`, `category`, `import`, `update` 실행 시 아래 기본 카테고리를 만듭니다.

| 이름 | 용도 |
|---|---|
| `parts` | 부품 |
| `tools` | 장비·공구 |
| `edu` | 교육 |
| `transit` | 교통 |
| `food` | 식비 |
| `etc` | 기타 |

모든 카테고리를 삭제한 경우에도 다음 실행 시 기본값이 다시 만들어집니다.
거래에서 사용하는 카테고리는 삭제할 수 없습니다. 거래를 다른 카테고리로 옮기거나 삭제한 뒤 카테고리를 삭제해야 합니다.

## 저장 파일

거래·카테고리·예산은 UTF-8 JSONL 파일에 저장합니다. JSONL의 각 줄에는 JSON 객체 하나가 들어갑니다.
거래 번호 카운터는 별도의 JSON 파일로 관리합니다.
명령을 처음 실행할 때 `transactions.jsonl`, `categories.jsonl`, `budgets.jsonl`이 없으면 빈 파일을 자동으로 만듭니다. 기존 파일은 덮어쓰지 않습니다.

| 파일 | 내용 | 쓰기 방식 |
|---|---|---|
| `transactions.jsonl` | id, 타입, 날짜, 금액, 카테고리, 메모, 태그 | 단건 추가는 append, import·수정·삭제는 임시 파일 작성 후 `os.replace` |
| `categories.jsonl` | 카테고리 이름 | 추가는 append, 삭제는 `os.replace` |
| `budgets.jsonl` | 월별 예산 | 같은 월의 예산을 갱신한 뒤 `os.replace` |
| `meta.json` | 다음 거래 번호(`next_seq`) | `os.replace` |

거래 ID는 `TX-` 뒤에 최소 6자리 ASCII 숫자를 붙입니다. 예를 들어 `TX-000001`부터 시작하며 999999 다음에는 `TX-1000000`처럼 자릿수가 늘어납니다. 0 이하의 번호는 허용하지 않습니다. 새 번호를 먼저 확정한 뒤 거래를 저장합니다.
거래 저장이 실패하면 번호가 건너뛰어질 수 있습니다.
`next_seq`에는 bool을 제외한 양수 int만 허용합니다. 값이 기존 거래의 최대 번호 이하이면 추가·import를 거부하고 거래와 번호 파일을 유지합니다.
번호 파일이 없거나 비었을 때는 남아 있는 거래의 최대 번호 + 1부터 복구합니다. 삭제된 거래의 과거 번호까지 복구하지는 못합니다.
번호가 계속 증가한다는 보장은 정상적인 번호 파일을 유지하고 한 프로세스에서 사용하는 경우에 적용됩니다.
번호 검증 시 기존 거래 ID를 순회하므로, 거래 추가에도 파일 크기에 비례하는 읽기 비용이 발생합니다.

조회 결과는 generator로 반환하며, 요청 범위에 따라 정렬 방법을 나눕니다.

- `list --limit N`에서 N이 1,024 이하이면 전체 거래를 generator로 읽으면서 `heapq.nlargest`로 상위 N건만 메모리에 유지합니다. 정렬용 임시 파일은 만들지 않습니다.
- limit이 1,024보다 크거나 건수 제한이 없는 조회는 external merge sort를 사용합니다. 1,024건씩 정렬해 임시 JSONL 파일에 쓰고, 최대 32개 파일씩 merge합니다.
- `search`와 `export`는 원본 파일을 읽으며 조건을 먼저 적용한 뒤 일치하는 거래만 external merge sort로 정렬합니다.

`list --limit 5`처럼 적은 건수만 요청해도 원본 파일 전체를 읽습니다.
메모리에 모든 거래를 모으지는 않지만, 거래가 많을수록 읽기 비용이 늘어납니다.
external merge sort에는 임시 디스크 공간과 추가 I/O도 필요합니다. 조회가 끝나거나 generator를 닫으면 임시 파일을 삭제하며, 처리 중 오류가 나도 정리합니다.
`summary`는 원본 파일을 순회하며 해당 월의 금액을 집계합니다.

## CSV import/export

CSV는 UTF-8과 헤더를 사용합니다. export는 아래 순서로 열을 기록하며, import는 헤더 이름으로 각 값을 찾습니다.

| 열 | 필수 | 형식 |
|---|---|---|
| `date` | 예 | `YYYY-MM-DD`, 실제 날짜 |
| `type` | 예 | `income` 또는 `expense` |
| `category` | 예 | 등록된 카테고리 이름 |
| `amount` | 예 | 양수 정수 |
| `memo` | 아니오 | 문자열, 없으면 빈값 |
| `tags` | 아니오 | 쉼표로 구분한 태그 |

쉼표가 들어가는 셀은 CSV의 따옴표 규칙을 따릅니다.

```csv
date,type,category,amount,memo,tags
2026-10-01,expense,food,15000,점심,"meal,work"
```

- export는 `--month`, `--from`, `--to` 중 하나 이상의 조건이 필요합니다.
- CSV에는 거래 id를 넣지 않습니다. import할 때 새 id를 발급합니다.
- import는 중복 거래를 자동으로 제거하지 않습니다. 같은 파일을 다시 가져오면 거래가 다시 추가됩니다.
- 중복되거나 알 수 없는 헤더는 파일 전체를 거부합니다. `memo`, `tags` 열은 생략할 수 있습니다.
- 각 행의 열 개수가 헤더와 다르면 해당 행을 건너뜁니다. 쉼표가 들어가는 태그·메모는 위 예시처럼 따옴표로 묶어야 합니다.
- 따옴표 문법이 잘못되었거나 UTF-8로 읽을 수 없는 CSV는 파일 전체를 거부하며 거래를 저장하지 않습니다.
- 잘못된 행은 건너뛰고 행 번호·원인·힌트를 출력합니다. 유효한 행은 기존 거래와 합쳐 임시 파일에 쓴 뒤 `os.replace`로 저장합니다.
- 저장할 행이 하나도 없고 잘못된 행이 있었다면 종료 코드 1을 반환합니다. 유효한 행과 잘못된 행이 섞여 있으면 유효한 행을 저장하고 종료 코드 0을 반환합니다.
- export 대상이 앱의 데이터 파일이면 덮어쓰기를 거부합니다.

## 모듈 구조

| 모듈 | 책임 |
|---|---|
| `__main__.py` | `python -m budget_app` 진입점과 종료 코드 전달 |
| `cli.py` | argparse, 대화형 입력, 명령 실행, 결과와 오류 출력 |
| `service.py` | 카테고리 사용 규칙, 검색 조건, 월별 집계, import/export |
| `repositories.py` | 거래·카테고리·예산의 저장과 조회, top N 선택과 external merge sort |
| `storage.py` | JSONL 읽기·쓰기, 파일 교체, 거래 번호 관리 |
| `models.py` | dataclass 모델, 필드 검증, JSON/CSV 변환 |
| `parsing.py` | 날짜·금액·타입·태그·이름의 공통 parsing 규칙 |
| `formatting.py` | 거래 행과 요약의 출력 형식 |
| `decorators.py` | 로그·시간 측정·파일 오류 변환 |
| `errors.py` | 원인·힌트·종료 코드를 담는 예외 |
| `__init__.py` | 패키지 정의 |

`CLI → service → repository → storage` 순서로 호출합니다.
입력 parsing과 모델 검증은 공통 규칙을 사용하고, 출력 문자열은 `formatting.py`에서 만듭니다.

## 저장 형식과 안전성

JSONL은 한 줄씩 독립적으로 읽을 수 있고 금액과 태그 목록의 타입을 보존합니다.
조회 시에는 JSONL을 한 건씩 읽어 상위 N건을 선택하거나, 일정한 건수씩 정렬해 임시 파일을 merge합니다. CSV는 스프레드시트 등 다른 도구와 데이터를 교환할 때 사용합니다.

수정·삭제·import는 기존 파일을 바로 덮어쓰지 않습니다.
새 내용을 같은 폴더의 임시 파일에 기록하고 `flush`와 `fsync`를 실행한 뒤 `os.replace`로 교체합니다.
교체 전에 오류가 나면 임시 파일을 지우고 원본을 유지합니다. export도 같은 방식으로 작성합니다.

이 방식은 파일 하나를 교체할 때의 안전성을 높입니다. 여러 파일을 묶는 transaction이나 동시 실행 간 잠금은 제공하지 않으므로 같은 데이터 폴더를 여러 프로세스에서 동시에 수정하지 않아야 합니다.

## Decorator와 type hint

서비스 메서드에는 다음 decorator를 적용합니다.

```python
@handle_errors  # OSError를 StorageError로 변환
@timed          # 실행 시간을 DEBUG 로그로 기록
@logged         # 호출 시작·완료를 DEBUG 로그로 기록
def add_transaction(self, draft: NewTransaction) -> Transaction: ...
```

로그는 stderr로 보내므로 stdout의 명령 결과와 분리됩니다. `--verbose`를 지정하면 DEBUG 로그가 표시됩니다.
`iter_*` 메서드에는 `timed`를 적용하지 않습니다. generator 함수에 적용하면 실제 순회 시간이 아니라 iterator를 만드는 시간만 측정하기 때문입니다.

함수·메서드와 dataclass 필드에 type hint를 사용합니다.
타입이나 허용 값이 정해진 필드는 `Literal`, `Iterator[Transaction]` 등으로 표시합니다.
모델은 `frozen=True, slots=True`인 dataclass이며, 값 변경은 `dataclasses.replace`로 새 객체를 만드는 방식입니다.

## 오류와 종료 코드

오류는 stdout에 `[오류] <원인>`과 `[힌트] <해결 방법>`으로 출력합니다.
traceback은 출력하지 않습니다. decorator의 실행 로그는 stderr로 보냅니다.

| 상황 | 종료 코드 |
|---|---:|
| 성공 | 0 |
| 입력·저장 데이터 오류, 없는 id, 카테고리 충돌, 파일 오류 | 1 |
| 잘못된 명령·옵션, 필수 옵션 누락 | 2 |

## 테스트와 성능 측정

```bash
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python scripts/bench_100k.py
```

테스트와 성능 측정은 임시 폴더를 사용하며 저장소의 `data/`는 변경하지 않습니다.

- `test_models.py`: parsing, 모델 검증, 데이터 변환, 6자리 이후 ID, 빈 달의 요약 형식
- `test_storage.py`: 날짜·ID 순서, top N 선택과 merge, 파일 교체 실패, 거래 번호 복구
- `test_cli.py`: 실제 CLI 프로세스의 명령·오류·저장 유지, 초기 파일 생성, CSV 오류 처리
- `test_bench_units.py`: 운영체제별 최대 RSS 단위 변환

성능 측정 스크립트는 임시 폴더에 거래 10만 건을 만들고 목록·검색의 실행 시간과 자식 프로세스의 최대 RSS를 출력합니다.
조회마다 전체 파일을 읽으므로 실행 시간은 데이터 크기의 영향을 받습니다. external merge sort의 임시 디스크 사용량은 정렬할 거래 수에 따라 증가합니다.
측정 결과는 실행 환경과 데이터에 따라 달라집니다. 조회 성능이 중요해지면 인덱스나 SQLite 도입을 검토할 수 있습니다.

코드를 읽을 때 참고할 파일과 테스트는 [REFERENCE.md](REFERENCE.md)에 정리했습니다.
