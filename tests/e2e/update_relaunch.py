"""업데이트 교체·재실행 실험 (#48). CI에서 Windows·Linux로 돌린다.

실제 app.updater로 onefile 앱 V1이 V2를 끼워 넣고 종료하면, 도우미
스크립트가 V1이 사라지길 기다렸다가 교체하고 V2를 다시 띄운다.
V2가 제대로 떠서 표식 파일에 'V2 ok'를 남기는지 본다.

    python tests/e2e/update_relaunch.py

PyInstaller가 필요하다. 앱 두 개를 빌드하므로 1~3분 걸린다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EXE = "SchoolNote.exe" if sys.platform == "win32" else "SchoolNote"

PROGRAM = '''
import os, sys
from pathlib import Path

VERSION = "{version}"
with Path(os.environ["E2E_MARKER"]).open("a") as out:
    # 어느 임시 폴더에서 떴는지도 남긴다. 옛 앱의 폴더를 이어 쓰면 버그다.
    out.write(f"{{VERSION}} ok {{getattr(sys, '_MEIPASS', '')}}\\n")

if VERSION == "V1":
    from app import updater
    updater.launch_replacer(Path(os.environ["E2E_STAGED"]), Path(sys.executable).resolve())
'''


def build(work: Path, version: str) -> Path:
    source = work / f"prog_{version}.py"
    source.write_text(PROGRAM.format(version=version), encoding="utf-8")
    subprocess.run(
        [
            # 실제 배포본(schoolnote.spec)처럼 콘솔 없는 GUI 앱으로 만든다.
            # Windows는 콘솔/GUI 부트로더가 달라 콘솔 앱으로는 재현되지 않는다.
            sys.executable, "-m", "PyInstaller", "--onefile", "--windowed", "--noconfirm",
            "--log-level", "WARN", "--name", "SchoolNote",
            "--distpath", str(work / f"dist_{version}"),
            "--workpath", str(work / f"build_{version}"),
            "--specpath", str(work / f"spec_{version}"),
            "--paths", str(ROOT), str(source),
        ],
        check=True,
    )
    return work / f"dist_{version}" / EXE


def main() -> int:
    # CI의 Windows 콘솔은 cp1252라 한글을 찍다 죽는다
    sys.stdout.reconfigure(encoding="utf-8")
    # resolve()로 긴 경로를 쓴다. CI 임시 폴더는 RUNNER~1 같은 8.3 짧은 이름이라,
    # 그대로 쓰면 updater가 다시 띄우는 경로(긴 이름)와 달라져 버그가 가려진다.
    # 실제 사용자 경로(C:\\Users\\ham\\…)는 짧은 이름이 아니다.
    work = Path(tempfile.mkdtemp(prefix="sn-e2e-")).resolve()
    v1, v2 = build(work, "V1"), build(work, "V2")

    install = work / "install"
    workspace = install / ".SchoolNote-update"
    workspace.mkdir(parents=True)
    target = install / EXE
    staged = workspace / f"new-{EXE}"
    shutil.copy2(v1, target)
    shutil.copy2(v2, staged)
    marker = work / "marker.txt"

    env = {**os.environ, "E2E_MARKER": str(marker), "E2E_STAGED": str(staged)}
    subprocess.run([str(target)], env=env, check=True, timeout=60)

    deadline = time.monotonic() + 90
    while time.monotonic() < deadline:
        if marker.exists() and "V2 ok" in marker.read_text(encoding="utf-8"):
            break
        time.sleep(0.5)

    log = marker.read_text(encoding="utf-8") if marker.exists() else "(없음)"
    replaced = target.read_bytes() == v2.read_bytes()
    print(f"표식:\n{log}")
    print(f"교체됨: {replaced}")
    print(f"작업 폴더 정리됨: {not workspace.exists()}")
    homes = {
        line.split(" ", 2)[0]: line.split(" ", 2)[2]
        for line in log.splitlines()
        if line.count(" ") >= 2
    }
    # 옛 폴더가 우연히 남아 있으면 이어 써도 뜬다(Windows CI가 그렇다).
    # 그래서 뜬 것만 보지 않고, 새 버전이 자기 폴더로 떴는지까지 본다.
    fresh = bool(homes.get("V2")) and homes.get("V2") != homes.get("V1")
    print(f"V1 폴더: {homes.get('V1')}")
    print(f"V2 폴더: {homes.get('V2')}")
    print(f"새 버전이 자기 폴더로 떴다: {fresh}")
    ok = replaced and "V2 ok" in log and fresh
    print("성공" if ok else "실패: 새 버전이 다시 뜨지 않았다")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
