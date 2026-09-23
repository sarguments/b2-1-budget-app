# b2-1-budget-app

파일 기반 용돈 기입장 콘솔 앱 (Python 3.10 이상, 표준 라이브러리만 사용).

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

외부 패키지는 설치하지 않습니다. 기능 명령은 구현·검증한 뒤 추가합니다.

## 준비 상태
패키지 진입점과 도움말 골격을 준비했습니다. 2026-09-23 로컬 Python 3.14.3 가상환경에서 도움말 출력을 확인했습니다.
거래 기능은 아직 구현하지 않았습니다. 기능은 작성자가 단계별로 직접 구현합니다.
