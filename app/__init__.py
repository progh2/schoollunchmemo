"""학교쪽지 (SchoolNote) — 급식·학사일정 데스크톱 포스트잇 위젯."""

from __future__ import annotations

#: 영문 식별자. 설정 경로, 자동 시작 레지스트리 값 이름,
#: 단일 인스턴스 소켓 이름, 실행 파일 이름에 쓰인다. 바꾸면 기존 사용자의
#: 설정이 끊기므로 마이그레이션 없이 건드리지 않는다.
APP_NAME = "SchoolNote"

#: 화면에 보이는 이름. 이쪽은 자유롭게 바꿀 수 있다.
APP_DISPLAY_NAME = "학교쪽지"

VERSION = "0.1.0"

NEIS_PORTAL_URL = "https://open.neis.go.kr"
REPO_URL = "https://github.com/progh2/schoollunchmemo"
ISSUES_URL = f"{REPO_URL}/issues"
LICENSE_NAME = "MIT"

AUTHOR_NAME = "Gihun Ham"
AUTHOR_URL = "https://github.com/progh2"

__all__ = [
    "APP_NAME",
    "APP_DISPLAY_NAME",
    "VERSION",
    "NEIS_PORTAL_URL",
    "REPO_URL",
    "ISSUES_URL",
    "LICENSE_NAME",
    "AUTHOR_NAME",
    "AUTHOR_URL",
]
