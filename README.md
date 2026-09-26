# b2-1-budget-app

파일 기반 용돈 기입장 콘솔 앱 (Python 3.10 이상, 표준 라이브러리만 사용).
`python -m budget_app <명령> [옵션]` 형식으로 10개 기능을 제공한다:
add / list / search / summary / budget(set·list) / category(add·list·remove) / update / delete / import / export.

## 이 앱의 소재

로봇 학습과 취미 프로젝트에 들어간 지출을 기록하는 용도로 씁니다. 기능·명령·저장 구조는 미션 원문 요구를 그대로 따르고, 소재만 아래처럼 잡습니다.

- 기본 카테고리 후보(저장 파일이 비었을 때 자동 생성하는 안을 택할 경우): `parts`(부품), `tools`(장비), `edu`(교육), `transit`(교통), `food`(식비), `etc`(기타)
- 예시 데이터 소재: 로봇 부품 구매, 키트와 공구, 온라인 강의, 교육장 왕복 교통비

> 이 절의 후보안은 구현되었어요. 데이터 파일(categories.jsonl)이 비어 있으면 위 6개 카테고리를 자동 생성하고(안 A), 실제 명령 예시와 import·export CSV 스키마는 아래에서 확인할 수 있습니다.

## 개발 환경
Python 3.10 이상과 표준 라이브러리만 사용합니다. 외부 패키지를 설치하지 않습니다.

### 새 환경에서 준비

Git을 설치한 뒤 새 기기에서 저장소를 받습니다.

```bash
git clone https://github.com/sarguments/b2-1-budget-app.git
cd b2-1-budget-app
```

Python 3.10 이상을 설치한 뒤 저장소 루트에서 실행합니다. 가상환경은 기기마다 새로 만듭니다.

```bash
python3 --version
python3 -m venv .venv
.venv/bin/python --version
.venv/bin/python -m budget_app --help
```

외부 패키지는 설치하지 않습니다. 10개 기능 명령은 모두 구현·검증되어 있습니다(2026-09-26, 로컬 Python 3.14.3 가상환경에서 아래 예시 출력과 테스트·벤치를 확인).

## 실행 방법

저장소 루트에서 실행합니다(`-m` 방식, 설치 불필요).

```bash
.venv/bin/python -m budget_app --help                    # 전체 명령
.venv/bin/python -m budget_app add                       # 대화형 거래 입력
.venv/bin/python -m budget_app list --limit 20           # 최신 추가순 목록
.venv/bin/python -m budget_app search --from 2024-01-01 --to 2024-01-31 --type expense
.venv/bin/python -m budget_app summary --month 2024-01 --top 3
.venv/bin/python -m budget_app budget set --month 2024-01 --amount 500000
.venv/bin/python -m budget_app budget list
.venv/bin/python -m budget_app category add robot-kit
.venv/bin/python -m budget_app category list
.venv/bin/python -m budget_app category remove edu
.venv/bin/python -m budget_app update --id TX-000001 --memo 도시락 --tags lunch,ref
.venv/bin/python -m budget_app delete --id TX-000001
.venv/bin/python -m budget_app import --from backup.csv
.venv/bin/python -m budget_app export --out backup.csv --month 2024-01
```

- 전역 옵션: `--data-dir DIR`(저장 디렉터리, 기본 `./data`), `--verbose`(데코레이터 로그·소요 시간을 stderr에 출력). 서브커맨드 앞에 붙인다.
- 모든 옵션은 `--`(더블대시) 계열이고, 모든 (서브)커맨드는 `--help`를 지원합니다.
- 성공 시 종료 코드 0, 오류는 1(도메인·데이터) 또는 2(사용법·인수)를 반환합니다. 스택 트레이스는 출력하지 않습니다.

## 저장 파일 위치·형식

`--data-dir` 지정 경로(기본 `./data`)에 **JSONL(1줄 = 1 JSON 객체, UTF-8)** 파일 4개로 저장합니다.

| 파일 | 내용 | 쓰기 방식 |
|---|---|---|
| `transactions.jsonl` | 거래(id·타입·날짜·금액·카테고리·메모·태그) | 단건 add=append, import·수정·삭제=임시 파일 재작성 후 원자 교체 |
| `categories.jsonl` | 카테고리 이름 | 추가=append, 삭제=원자 교체 |
| `budgets.jsonl` | 월 예산(month·amount), 한 달 한 개 | upsert=원자 교체 |
| `meta.json` | 거래 id 채번 카운터(`{"next_seq": n}`) | 원자 교체 |

거래 id는 `TX-` + 6자리 영(0) 채번(`TX-000001`)으로 **단조 증가**합니다. `meta.json`을 별도로 두는 이유: 마지막 거래를 삭제 후 재추가해도 그 id가 재사용되지 않게, 채번 상태를 파일에만 의존하지 않고 분리해서 관리합니다. 확정 순서는 단건 add가 `peek → meta 원자 쓰기 → 거래 append`이고, import는 `peek → advance_by → 기존분+유효분 재작성(os.replace)`으로 채번 순서는 같습니다. 거래 쓰기가 실패해도 번호는 건너뛸 뿐 재사용되지 않습니다. 만약 `meta.json`이 없어지거나 비어도 거래 파일에 남은 최대 id + 1부터 채번을 이어가므로 id가 중복되지 않습니다(거래까지 없을 때만 1부터 시작).

list는 파일을 처음부터 읽지 않습니다. `storage.iter_lines_reversed`가 파일 **끝에서 블록(기본 8KiB) 단위로 거꾸로** 읽어 최근 추가분부터 yield하므로, `list --limit 5`는 파일이 14MiB(10만 건)여도 5건+블록만 읽고 거기서 멈춥니다. 반면 `search`도 역순 생성기를 쓰지만 조건에 맞는 건을 찾으려면 끝에서 시작해 **결국 전 파일을 훑어야** 하므로(중단 조건이 없음), 읽는 양 자체는 전체입니다.

`categories.jsonl`이 0바이트가 되는 경우는 첫 실행과 같은 시드 조건입니다. 카테고리를 **전부 삭제**한 뒤에도 다음번 시드 명령(`add`·`category`·`import`·`update`)을 실행하면 위 기본 6개 카테고리로 자동 재시드됩니다(안 A).

## 주요 명령 예시 (실제 검증 출력)

아래는 로컬 검증 세션(`/tmp/b2ref`, Python 3.14.3)에서 나온 실제 출력입니다.

```text
$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref category list   # 첫 실행: 기본 카테고리 자동 생성
parts
tools
edu
transit
food
etc

$ printf '2024-01-15\nexpense\nfood\n15000\n점심\nmeal\n' | .venv/bin/python -m budget_app --data-dir /tmp/b2ref add
날짜(YYYY-MM-DD): 타입(income/expense): 카테고리: 금액(양수): 메모(선택): 태그(쉼표로 구분, 없으면 엔터): [저장 완료] id=TX-000001

$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref list --limit 3
TX-000001 | 2024-01-15 | expense | food | 15000 | 점심 #meal

$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref budget set --month 2024-01 --amount 500000
[저장 완료] 2024-01 예산 500000원

$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref summary --month 2024-01 --top 3
2024-01 요약
총 수입: 0원
총 지출: 15000원
잔액: -15000원
예산: 500000원 (사용률 3.0%)
지출 TOP 1
1. food: 15000원

$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref export --out /tmp/b2ref-export.csv --month 2024-01
[완료] /tmp/b2ref-export.csv (1 records)

$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref import --from /tmp/b2ref-export.csv
[완료] imported=1, skipped=0
```

행 표시 규약(직접 선택, README 문서화): `id | 날짜 | 타입 | 카테고리 | 금액 | 메모`를 `" | "`로 결합하고, 태그가 있으면 끝에 ` #tag1,tag2`를 붙입니다. 메모가 비면 해당 칸은 빈 채로 구분자만 남습니다. summary의 `지출 TOP N`은 등록된 카테고리가 요청보다 적으면 실제 개수를 출력합니다(예시에서는 지출 카테고리가 food 1개라 `TOP 1`).

오류 경로 예시(트레이스 없음, 원인+힌트):

```text
$ printf '2024-13-40\nexpense\nfood\n-5\nx\ny\n' | .venv/bin/python -m budget_app --data-dir /tmp/b2ref add
날짜(YYYY-MM-DD): [오류] 날짜 '2024-13-40'는 달력에 존재하지 않습니다.
[힌트] 월(01~12)과 일 범위를 확인하세요.
... (잘못된 값마다 재입력 요구) ...
날짜(YYYY-MM-DD): [오류] 입력이 끝나 거래 추가를 중단했습니다.
[힌트] 다시 실행하거나, 파이프 입력이라면 필드 순서대로 값을 보내세요.
$ echo $?   # 입력 소진으로 종료
1

$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref delete --id TX-999999
[오류] id 'TX-999999' 거래가 없습니다.
[힌트] list나 search로 정확한 id(TX-000001 형식)를 확인하세요.
$ echo $?
1

$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref export --out /tmp/x.csv
[오류] export 조건이 없습니다.
[힌트] --month YYYY-MM 또는 --from/--to 중 하나 이상을 지정하세요.
$ echo $?
2
```

## import/export CSV 스키마

UTF-8, 헤더 포함, 열 순서 고정:

| 열 | 필수 | 형식 | 설명 |
|---|---|---|---|
| `date` | 필수 | YYYY-MM-DD | 거래 날짜(실존 날짜 검증) |
| `type` | 필수 | income/expense | 타입 |
| `category` | 필수 | 등록된 이름 | 미등록 카테고리는 행 단위 스킵 |
| `amount` | 필수 | 양수 정수 | 금액 |
| `memo` | 선택 | 문자열 | 메모(없으면 빈값) |
| `tags` | 선택 | 쉼표 구분 | 태그 목록 |

CSV에 id는 없습니다(import 시 새 id를 채번해 병합). export는 `--month` 또는 `--from/--to` 중 하나 이상을 요구합니다(없으면 사용법 오류 2).

**부분 성공 정책(import)**: 모든 줄을 먼저 검증하고, 유효 줄만 **기존분과 합쳐 임시 파일에 스트리밍한 뒤 `os.replace`로 원자 교체**합니다(update/delete와 같은 전략). 즉 한 줄씩 append하지 않으므로, 쓰기 도중 실패해도 원본 `transactions.jsonl`은 바뀌지 않습니다. 잘못된 줄은 저장하지 않고 사유(줄 번호+원인+힌트)를 출력합니다. 모든 줄이 스킵되어 저장분이 0건이면 요약을 출력한 뒤 [오류]/[힌트]와 함께 종료 코드 1로 끝냅니다(일부라도 저장된 혼합 결과는 0).

```text
$ .venv/bin/python -m budget_app --data-dir /tmp/b2ref import --from partial.csv
[완료] imported=1, skipped=2
  줄 3: 카테고리 'ghost' 미등록 (힌트: category add로 먼저 등록하세요.)
  줄 4: 타입 'oops'는 알 수 없습니다. (힌트: income 또는 expense만 입력할 수 있습니다.)
```

## 모듈 구조와 책임 (11개 모듈)

| 모듈 | 책임 |
|---|---|
| `__main__.py` | `python -m` 진입점. `main() -> int`로 cli 위임, 종료 코드를 SystemExit으로 전달 |
| `cli.py` | argparse 파서(_AppParser가 인수 오류를 종료코드 2로 변환), 대화형 add 입력 루프, 명령 dispatch, [오류]/[힌트]·종료 코드 처리, --verbose 로그 설정 |
| `service.py` | 비즈니스 규칙 단일 파사드(BudgetService): 카테고리 등록 요건, 사용 중 보호, 필터(SearchCriteria) AND 결합, 월 집계, import 부분 성공 |
| `repositories.py` | 모델 ↔ 파일 창구: TransactionRepository, CategoryRepository, BudgetRepository. 거래 수정·삭제의 스트리밍 재작성 |
| `storage.py` | 저장 기반 도구: 역순 줄 생성기(iter_lines_reversed), JsonlStore(append·원자 재작성), SequenceFile(id 채번) |
| `models.py` | 검증된 데이터(frozen dataclass)와 JSONL/CSV 승격·직렬화. 생성 시점 검증으로 하위 계층은 재검증하지 않음 |
| `parsing.py` | 경계 형식 규칙: parse_date/month/amount/type/tags, 카테고리 이름 검증, id 형식. cli·models·repositories가 공유 |
| `formatting.py` | stdout 표시 문자열 순수 함수(행 서식·summary 블록) |
| `decorators.py` | @logged/@timed/@handle_errors와 stderr 로거 설정(명령 출력(stdout)과 분리) |
| `errors.py` | AppError 계통: cause·hint·exit_code(도메인 1 / 사용법 2) |
| `__init__.py` | 패키지 문서 |

데이터 흐름: `cli`(문자열 인수) → `parsing`(검증된 타입) → `models`(검증된 값 객체) → `service`(규칙) → `repositories`(모델↔dict) → `storage`(dict↔줄). 검증은 경계 한 곳, 출력 서식은 formatting 한 곳에 모읍니다.

## 클래스별 역할

| 클래스 | 역할 |
|---|---|
| `Transaction` / `NewTransaction` / `Category` / `Budget` | 불변 값 객체. 필드 자체 검증(id 형식·실존 날짜·양수 금액 등) |
| `TransactionPatch` | update의 옵션 기반 변경분(None이 아닌 필드만 교체). `apply_patch`로 병합 |
| `SearchCriteria` | search/export 필터 데이터를 AND로 묶어 `matches(tx)` 한 곳에서 판단 |
| `JsonlStore` | JSONL 파일 1개의 append/순방향·역순 읽기/임시파일 원자 재작성 |
| `SequenceFile` | meta.json 채번 카운터(peek/advance). id 단조 증가의 근거 |
| `TransactionRepository` | 거래 저장·id 채번 연결·수정/삭제 스트리밍 재작성 |
| `CategoryRepository` | 카테고리 CRUD + 첫 실행 기본 카테고리 시드 |
| `BudgetRepository` | 월 예산 upsert(한 달 한 개)·조회·목록 |
| `BudgetService` | 위 저장소 3개를 조합하는 파사드. 데코레이터 적용 지점 |

## JSONL vs CSV 선택 근거

저장 포맷은 **JSONL을 선택**했고, CSV는 import/export 교환 용도로만 씁니다.

| 관점 | JSONL | CSV |
|---|---|---|
| 한 줄이 완전한 레코드 | 예 — 역순·부분 읽기와 계약 | 아니오 — 헤더/인용/줄바꿈 이스케이프 때문에 임의 줄부터 읽기 위험 |
| 타입 보존 | 예 — amount가 int로 저장 | 아니오 — 전부 문자열, 열별 재파싱 필요 |
| 선택 필드(memo·tags) | 예 — 태그 목록을 배열로 그대로 | 빈약 — 문자열 규칙(쉼표)을 재발명해야 함 |
| 메모에 쉼표·따옴표 | 큰 문제 없음(JSON 이스케이프) | 인용 규칙 필수, 사용자 데이터라 실수하기 쉬움 |
| 사람이 직접 편집 | 읽기 가능하나 구문 오류 쉬움 | 엑셀·스프레드시트 관용 |
| 기계 간 교환 | 보통 | 높음(표준 스키마) |

용돈 기입장의 핵심 요구가 "list/search가 **최신순으로, 전체 로드 없이**"이기 때문에, 한 줄이 완전자립인 JSONL이 역순 생성기와 잘 맞습니다. CSV의 강점(교환)은 export/import 경로에서 그대로 살립니다.

## 10만 건 실측: 병목 후보와 개선안

`scripts/bench_100k.py`가 임시 디렉터리에 10만 건(14MiB)을 만들고 실제 CLI로 측정합니다(로컬 실측 1회).

| 측정 | 결과(여러 회차 변동 범위) |
|---|---|
| `list --limit 5` (프로세스째) | 약 0.4초 — 대부분 파이썬 기동. 역순 읽기 자체는 1ms 미만 |
| `search --category parts` (전체 역순) | 8~12초 |
| `search --q 강좌` (전체 역순) | 6~9초 |
| 자식 프로세스 최대 RSS | 약 19MB — 파일 크기와 무관하게 일정 |
| 프로세스 내 전체 파싱 10만 건 | 4.7~9.2초 |

**병목 후보 판단**: 읽기 범위는 `list --limit`만 유한합니다(역순으로 N건을 채우면 중단). `summary`는 `--month`로 거르더라도 **전체 거래를 순방향으로 훑어야** 하고, `search`도 조건 충족 건을 찾으려면 끝에서 시작해 전 파일을 훑습니다. 즉 summary·search 둘 다 전체 스캔이라 병목이 **디스크 I/O가 아니라 JSON 파싱·줄 순회(CPU)**입니다(파일 14MiB인데 파싱이 초 단위). 정렬은 없음 — 저장 순서=추가 순서로 최신순을 유지합니다.

**구체적 개선안**:
1. 인덱스 파일(날짜→byte offset 또는 카테고리별 id 목록)을 만들어 search가 조건에 맞는 블록만 seek.
2. 파싱 단가 낮추기: `--category`만 필요하면 json 전체 대신 문자열 부분 검사로 1차 필터링하고, 통과 건만 역 직렬화(두 패스).
3. SQLite 표준 라이브러리 이관 — 실데이터에서 JSONL의 'append 단순함'보다 질의 성능이 중요해지면 채택(마이그레이션은 import 재사용).
4. 자주 쓰는 달집계(summary)를 월별 합계 캐시로 적어두고 거래 쓰기에 무효화.

## update/delete 원자적 교체 전략 (임시 파일 + os.replace)

1. 원본을 순방향으로 스트리밍하면서 대상 줄만 교체/제외한 새 내용을 `transactions.jsonl.<pid>.tmp`에 기록(전체 목록을 메모리에 담지 않음).
2. temp를 닫기 전 `flush + fsync`으로 디스크에 반영.
3. `os.replace(temp, 원본)` — POSIX 원자적 rename이라 읽는 쪽은 '옛날 파일' 아니면 '새 파일'만 본다.
4. **실패 시 롤백**: 1~2단계 예외(검증 오류·디스크 오류)면 temp만 삭제하고 원본은 무변경. 재작성 도중 데이터 오류가 나면(예: 손상 줄) 3단계까지 도달하지 못하므로 "반쯤 바뀐 파일"이 생길 수 없습니다.
5. 대상 id가 없으면 재작성이 완료된 뒤 NotFoundError를 낸 — 교체 대상이 없어 결과 파일은 원본과 동일합니다.

export CSV도 같은 전략(임시 파일 → os.replace)으로, 쓰기 실패 시 반쪽 CSV를 남기지 않습니다. 그리고 `--out`이 앱 데이터 파일(`transactions.jsonl` 등 4개)과 같은 경로면 자료 유실을 막기 위해 거부합니다([오류]/[힌트]·종료 코드 1).

## 데코레이터 사용 예 (decorators.py)

```python
@handle_errors          # OSError → [오류]/[힌트]를 담은 StorageError로 변환
@timed                  # 소요 시간 ms를 DEBUG 로그로
@logged                 # 시작/완료 흔적을 DEBUG 로그로
def add_transaction(self, draft: NewTransaction) -> Transaction: ...
```

- 출력은 stderr 로거 전용이라 stdout의 명령 결과와 섞이지 않습니다.
- `--verbose`를 켜면 DEBUG로 드러나고, 끄면 CRITICAL 스레시홀드로 조용해집니다(동작은 동일).
- 지연 생성기(list/search)는 감싸지 않습니다 — 생성기 함수를 데코레이트하면 'iterator 생성'까지만 재서 오해를 부르기 때문입니다.

## 타입 힌트 정책

- 모든 함수·메서드 시그니처와 dataclass 필드에 타입 힌트를 붙였습니다(`from __future__ import annotations` 사용).
- `TransactionType = Literal["income", "expense"]`처럼 값 집합이 정해진 필드는 Literal로, `Iterator[Transaction]`, `dict[str, object]` 등 반환 컨테이너까지 명시했습니다.
- 저장된 JSON을 읽는 지점(`from_json_dict`)이 신뢰 경계입니다: 여기서 타입을 검사해 모델을 만들고, 내부 코드에서는 검증된 타입만 다룹니다.
- 모든 모델은 `frozen=True, slots=True`: 생성 후 변경이 없고(변경은 `dataclasses.replace`로 새 객체), 실수 대입이 즉시 잡힙니다.

## 오류 처리와 종료 코드

- 사용자에게 보이는 오류는 전부 두 줄: `[오류] <원인>` + `[힌트] <해결 힌트>` (stdout 출력. 파이프로 결과를 받는 스크립트에서도 보이게 함 — 데코레이터 로그만 stderr).
- 스택 트레이스는 출력하지 않습니다. argparse 실패도 `_AppParser.error`가 [오류]/[힌트]로 변환하고, 예측 못 한 예외도 최외곽에서 잡혀 안내 문구로 나갑니다. `--verbose`여도 트레이스는 나오지 않습니다(내부 오류는 stderr에 `[로그] ERROR 예상치 못한 내부 오류: ...` 한 줄만 남음). 파일·권한 오류(OSError)는 데코레이터를 거치지 않은 경로에서도 [오류]/[힌트]로 변환됩니다.

| 상황 | 출력 | 종료 코드 |
|---|---|---|
| 성공 | 명령 결과 | 0 |
| 입력값·저장 데이터 형식 오류(ValidationError) | [오류]+[힌트] | 1 |
| 대상 id 없음(NotFoundError) | [오류]+[힌트] | 1 |
| 사용 중 카테고리 삭제·중복(category ConflictError) | [오류]+[힌트] | 1 |
| 파일·권한 문제(StorageError) | [오류]+[힌트] | 1 |
| 대화형 입력 EOF/Interrupt | [오류]+[힌트] | 1 |
| import 전부 스킵(imported=0, skipped>0) | [완료] 요약 + [오류]+[힌트] | 1 |
| export --out이 앱 데이터 파일 | [오류]+[힌트] | 1 |
| 예상치 못한 내부 오류 | [오류]+[힌트] | 1 |
| 잘못된 명령·옵션, 필수 옵션 누락, 조건 없는 export(UsageError) | [오류]+[힌트] | 2 |

## 테스트·벤치 실행

```bash
.venv/bin/python -m unittest discover -s tests -v   # 단위+종단간 99개
.venv/bin/python scripts/bench_100k.py              # 10만 건 실측(임시 디렉터리)
```

테스트는 `test_models.py`(경계 검증), `test_storage.py`(역순 생성기·원자 교체·채번 회복), `test_cli.py`(실제 프로세스 10개 명령·오류 코드·프로세스 간 영속성·트레이스 부재), `test_bench_units.py`(ru_maxrss 단위 정규화)로 나뉩니다. 데이터는 전부 임시 디렉터리에 만들므로 저장소 `data/`를 건드리지 않습니다.

## 구현 상태

10개 명령·4개 저장 파일·스트리밍·데코레이터·원자 교체·부분 import 정책을 구현하고, 2026-09-26 로컬(Python 3.14.3)에서 unittest 99개 통과와 위 검증 예시의 종료 코드를 확인했습니다. 참고용 모범 답안 브랜치(`ref/b2-1-solution`)의 대응 설명은 `REFERENCE.md`를 보세요(제출용 아님).
