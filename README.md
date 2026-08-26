# 학교쪽지 (SchoolNote)

> 오늘 우리 학교의 **급식 메뉴**와 **학사일정**을,  
> 책상 위 포스트잇처럼 바탕화면에 붙여두는 무료 데스크톱 위젯

**[🌐 홈페이지](https://progh2.github.io/schoollunchmemo/)** · **[⬇ 다운로드](https://github.com/progh2/schoollunchmemo/releases/latest)**

![Screenshot](./screenshot.png)

---

## ✨ 특징

- **포스트잇 UI** — 제목표시줄 없는 반투명 창. 드래그로 원하는 곳에 붙여두면 위치가 기억됩니다.
- **트레이 상주** — 숨겨도 트레이 아이콘은 항상 남습니다. 클릭하면 다시 표시.
- **자동 갱신** — 자정이 지나면 스스로 그날 정보를 가져옵니다.
- **날짜 탐색** — 마우스 휠이나 `‹ ›` 버튼으로 날짜를 넘깁니다.
- **알레르기 경고** — 내 알레르기가 들어간 음식을 빨갛게 강조합니다.
- **재료·원산지** — 포스트잇을 클릭하면 원산지·영양 정보가 펼쳐집니다.
- **인증키 불필요** — NEIS 공개 API를 그대로 사용합니다. 바로 쓸 수 있습니다.
- **서버 없음** — 앱이 NEIS API를 직접 호출합니다. 개인정보가 어디로도 전송되지 않습니다.
- **크로스플랫폼** — Windows / macOS / Linux

---

## 🚀 시작하기

### 실행 파일로 바로 사용 (권장)

[최신 릴리스](https://github.com/progh2/schoollunchmemo/releases/latest)에서 운영체제에 맞는 파일을 받아 압축을 풀고 실행합니다.

| OS | 파일 | 비고 |
|---|---|---|
| Windows | `SchoolNote-*-windows-x64.zip` | SchoolNote.exe 실행 |
| macOS | `SchoolNote-*-macos.zip` | SchoolNote.app 실행 |
| Linux | `SchoolNote-*-linux-x64.tar.gz` | SchoolNote 실행 |

처음 실행하면 설정 창이 열립니다. **학교** 탭에서 학교를 검색해 선택하면 바로 급식이 표시됩니다.

### 소스에서 직접 실행

**Windows** — `run.bat`을 두 번 클릭

**macOS / Linux**
```bash
./run.sh
```

**직접 실행**
```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m app
```

---

## 🗂 프로젝트 구조

```
schoollunchmemo/
├─ app/
│  ├─ __main__.py          # 진입점, 단일 인스턴스 보장, 로깅
│  ├─ controller.py        # 전체 흐름 조율 (조회 → 렌더 → 상태 표시)
│  ├─ tray.py              # 트레이 아이콘과 메뉴
│  ├─ sticky.py            # 포스트잇 위젯
│  ├─ settings_dialog.py   # 설정 창 (학교 / 표시 / 알레르기)
│  ├─ config.py            # 설정 로드·저장
│  ├─ autostart.py         # 부팅 시 자동 시작 등록
│  ├─ cache.py             # 날짜 단위 응답 캐시
│  ├─ allergens.py         # 알레르기 19종 코드와 매칭
│  ├─ scheduler.py         # 자정 롤오버 감지
│  ├─ workers.py           # 백그라운드 작업 실행기
│  ├─ neis/
│  │  ├─ client.py         # HTTP 호출, 타임아웃, 재시도
│  │  ├─ codes.py          # RESULT.CODE 분류
│  │  ├─ models.py         # School / MealMenu / ScheduleEvent
│  │  └─ parser.py         # 응답 정규화
│  └─ resources/
│     ├─ icons.py          # 아이콘 생성 (바이너리 없음)
│     └─ theme.py          # 포스트잇 색상 팔레트
├─ docs/                   # GitHub Pages 홈페이지
├─ tests/
├─ run.bat                 # Windows 실행 스크립트
├─ run.sh                  # macOS / Linux 실행 스크립트
├─ schoolnote.spec         # PyInstaller 빌드 설정
├─ requirements.txt
└─ requirements-dev.txt
```

---

## 🧪 테스트

```bash
pip install -r requirements-dev.txt
pytest -q
```

---

## 📦 빌드

```bash
pip install -r requirements-dev.txt
pyinstaller schoolnote.spec --noconfirm
```

macOS / Linux는 해당 OS에서 직접 빌드해야 합니다 (크로스 빌드 불가).  
태그를 push하면 GitHub Actions가 세 플랫폼을 자동 빌드합니다.

---

## 🔌 사용하는 API

NEIS 교육정보 개방 포털 공개 API (인증키 불필요, 일 1000건 제한)

| 서비스 | 엔드포인트 | 용도 |
|---|---|---|
| 학교기본정보 | `/hub/schoolInfo` | 학교 검색 |
| 급식식단정보 | `/hub/mealServiceDietInfo` | 급식 조회 |
| 학사일정 | `/hub/SchoolSchedule` | 행사·일정 조회 |

---

## ⚖️ 라이선스 및 출처

- 급식·학사일정 데이터: **교육부 NEIS 교육정보 개방 포털** (<https://open.neis.go.kr>)
- 본 프로젝트는 교육부·시도교육청과 무관한 비공식 개인 프로젝트입니다.
