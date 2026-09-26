"""budget_app — 파일 기반 용돈 기입장 콘솔 앱 (표준 라이브러리만 사용).

계층 구조: cli(인수·출력) → service(규칙) → repositories(저장 창구) →
storage(JSONL·역순 생성기·채번) + models(검증된 데이터) + parsing(형식 규칙)
+ decorators(로그·시간·예외) + formatting(표시 문자열) + errors(원인·힌트·종료 코드).
"""
