#!/usr/bin/env sh
# ---------------------------------------------------------------------------
# 급식쪽지 실행 스크립트 (macOS / Linux)
#
# 가상환경이 없으면 만들고, 패키지가 빠져 있으면 채운 뒤 앱을 띄운다.
# 두 번째 실행부터는 확인만 하고 바로 뜬다.
#
#   ./run.sh                터미널에 붙여서 실행 (Ctrl+C로 종료)
#   ./run.sh --background   터미널을 닫아도 계속 돌게 띄운다
# ---------------------------------------------------------------------------

set -eu

cd "$(dirname "$0")"

PY=".venv/bin/python"
PROBE='from PySide6.QtWidgets import QApplication; import requests, keyring'

BACKGROUND=0
case "${1:-}" in
    --background | -b)
        BACKGROUND=1
        shift
        ;;
esac

# 3.12 이상인 인터프리터를 찾는다. 이름이 여러 가지라 후보를 훑는다.
find_python() {
    for candidate in python3.14 python3.13 python3.12 python3 python; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c \
            'import sys; raise SystemExit(0 if sys.version_info >= (3, 12) else 1)' \
            >/dev/null 2>&1; then
            echo "$candidate"
            return 0
        fi
    done
    return 1
}

if [ ! -x "$PY" ]; then
    if ! base=$(find_python); then
        echo "[오류] Python 3.12 이상을 찾을 수 없습니다." >&2
        case "$(uname)" in
            Darwin) echo "       brew install python@3.12" >&2 ;;
            *)      echo "       sudo apt install python3.12 python3.12-venv" >&2 ;;
        esac
        exit 1
    fi
    echo "[급식쪽지] 가상환경을 만듭니다 (.venv)..."
    "$base" -m venv .venv
fi

# 필요한 패키지가 다 있는지 먼저 확인한다. 매번 pip을 돌리면 실행이 느려진다.
if ! "$PY" -c "$PROBE" >/dev/null 2>&1; then
    echo "[급식쪽지] 필요한 패키지를 설치합니다. 처음에는 몇 분 걸립니다..."
    "$PY" -m pip install --upgrade pip >/dev/null
    "$PY" -m pip install -r requirements.txt

    if ! "$PY" -c "$PROBE" >/dev/null 2>&1; then
        echo "[오류] 패키지는 설치했지만 Qt를 불러오지 못했습니다." >&2
        if [ "$(uname)" = "Linux" ]; then
            # PySide6 휠에는 Qt 실행 라이브러리가 다 들어 있지 않다
            echo "       Qt 실행 라이브러리가 빠졌을 수 있습니다:" >&2
            echo "       sudo apt install libegl1 libgl1 libxkbcommon0 \\" >&2
            echo "            libdbus-1-3 libfontconfig1" >&2
        fi
        exit 1
    fi
fi

if [ "$BACKGROUND" = "1" ]; then
    # 로그는 앱이 알아서 파일로 남기므로 표준 출력은 버린다
    nohup "$PY" run.py "$@" >/dev/null 2>&1 &
    echo "[급식쪽지] 백그라운드에서 실행했습니다 (PID $!). 종료는 트레이 메뉴에서."
    exit 0
fi

exec "$PY" run.py "$@"
