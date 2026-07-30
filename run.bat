@echo off
REM ---------------------------------------------------------------------------
REM 급식쪽지 실행 스크립트 (Windows)
REM
REM 이 파일을 두 번 클릭하면 된다. 가상환경이 없으면 만들고, 패키지가
REM 빠져 있으면 채운 뒤 앱을 띄운다. 두 번째 실행부터는 확인만 하고 바로 뜬다.
REM
REM   run.bat             트레이에 조용히 띄운다 (콘솔 창 없음)
REM   run.bat --console   콘솔을 열어 로그를 함께 본다
REM ---------------------------------------------------------------------------

REM 이 파일은 ANSI(한국어 Windows 기준 CP949)로 저장한다. cmd는 배치 파일을
REM 콘솔 코드페이지로 읽으므로, UTF-8로 저장하면 아래 한글 줄에서 따옴표와
REM 줄바꿈이 잘려 나가며 엉뚱한 명령이 실행된다. 줄바꿈도 CRLF여야 한다.

setlocal EnableExtensions
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
set "PYW=.venv\Scripts\pythonw.exe"
set "PROBE=from PySide6.QtWidgets import QApplication; import requests, keyring"

set "CONSOLE="
if /i "%~1"=="--console" set "CONSOLE=1"
if /i "%~1"=="-c" set "CONSOLE=1"

if not exist "%PY%" (
    echo [급식쪽지] 가상환경을 만듭니다 ^(.venv^)...
    call :find_python
    if not defined LAUNCHER goto :no_python
    %LAUNCHER% -m venv .venv
    if errorlevel 1 goto :venv_failed
)

REM 필요한 패키지가 다 있는지 먼저 확인한다. 매번 pip을 돌리면 실행이 느려진다.
"%PY%" -c "%PROBE%" >nul 2>&1
if errorlevel 1 (
    echo [급식쪽지] 필요한 패키지를 설치합니다. 처음에는 몇 분 걸립니다...
    "%PY%" -m pip install --upgrade pip >nul 2>&1
    "%PY%" -m pip install -r requirements.txt
    if errorlevel 1 goto :pip_failed
    "%PY%" -c "%PROBE%" >nul 2>&1
    if errorlevel 1 goto :import_failed
)

if defined CONSOLE (
    echo [급식쪽지] 실행합니다. 이 창을 닫으면 앱도 종료됩니다.
    "%PY%" run.py
    goto :done
)

REM 콘솔 창을 남기지 않으려면 창 없는 인터프리터로 띄우고 바로 빠져나온다.
if exist "%PYW%" (
    start "" "%PYW%" run.py
) else (
    start "" "%PY%" run.py
)
goto :done


:find_python
REM py 런처를 먼저 찾고, 없으면 PATH의 python을 쓴다.
set "LAUNCHER="
py -3 --version >nul 2>&1
if not errorlevel 1 (
    set "LAUNCHER=py -3"
    exit /b 0
)
python --version >nul 2>&1
if not errorlevel 1 set "LAUNCHER=python"
exit /b 0

:no_python
echo.
echo [오류] Python을 찾을 수 없습니다.
echo        https://www.python.org/downloads/ 에서 Python 3.12 이상을 설치하고,
echo        설치할 때 "Add Python to PATH"를 켜 주세요.
goto :fail

:venv_failed
echo.
echo [오류] 가상환경(.venv)을 만들지 못했습니다.
echo        Python 버전이 3.12 이상인지 확인해 주세요.
goto :fail

:pip_failed
echo.
echo [오류] 패키지를 설치하지 못했습니다. 네트워크 연결을 확인해 주세요.
goto :fail

:import_failed
echo.
echo [오류] 패키지는 설치했지만 Qt를 불러오지 못했습니다.
echo        .venv 폴더를 지우고 다시 실행해 보세요.
goto :fail

:fail
echo.
pause
exit /b 1

:done
endlocal
exit /b 0
