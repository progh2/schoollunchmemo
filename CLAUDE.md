# 급식쪽지 (SchoolNote) — 작업 노트

PySide6 데스크톱 포스트잇 위젯. NEIS 공개 API(인증키 없음, 일 1000건)로
급식·학사일정을 보여준다. 상세 설계는 `docs/PRD.md`, 구조는 `README.md` 참조.

## 컨텍스트 앵커
- intent: v0.3.1 릴리스 완료. 오픈 이슈 0개 상태로 마무리
- changes_made: 인증키 완전 제거, 달력·정보 탭 병합(PR #11 base 오류 복구),
  이름 '급식쪽지' 확정, 3플랫폼 자동 릴리스, 앱 아이콘(.ico/.icns) 임베드,
  PRD 현행화 + mermaid UML(README·PRD)
- decisions: 표시 이름은 급식쪽지 / 영문 식별자 SchoolNote는 불변(설정 경로 호환).
  아이콘은 icons.py 그림 기준으로 scripts/make_icons.py가 생성해 assets/에 커밋.
  빈 DDISH_NM row는 parse_meals에서 걸러 급식으로 세지 않는다(#12)
- next_steps: 백로그(여러 학교, 내일 급식 미리보기, 메뉴 알림, 주간 요약)는
  착수 전 이슈 등록부터

## 규칙
- 모든 작업은 GitHub 이슈로 추적하고 커밋 메시지에 `(#번호)` 연결
- 릴리스는 태그 push로 자동 (release.yml, 3플랫폼). 태그 전 로컬 `pytest -q` 확인
- run.bat은 CP949 인코딩 — 편집 시 iconv 경유
- 아이콘 그림을 바꾸면 `python scripts/make_icons.py` 재실행 (Pillow 필요)
