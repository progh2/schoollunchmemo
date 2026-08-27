"""앱 아이콘 파일(.ico/.icns) 생성.

app/resources/icons.py가 그리는 포스트잇 그림을 그대로 렌더해
실행 파일 임베드용 아이콘을 만든다. 결과물은 assets/에 커밋한다.

    python scripts/make_icons.py

다시 실행하면 덮어쓴다. 그림을 바꿨을 때만 실행하면 된다.
"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image  # noqa: E402
from PySide6.QtCore import QBuffer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.resources.icons import note_pixmap  # noqa: E402

# ICO는 Windows 탐색기·작업 표시줄 기준, ICNS는 macOS 요구 사이즈 전부
ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)
ICNS_SIZES = (16, 32, 64, 128, 256, 512, 1024)


def _render(size: int) -> Image.Image:
    """Qt가 그린 픽스맵을 PIL 이미지로 옮긴다."""
    pixmap = note_pixmap(size)
    buffer = QBuffer()
    buffer.open(QBuffer.OpenModeFlag.ReadWrite)
    pixmap.save(buffer, "PNG")
    return Image.open(io.BytesIO(bytes(buffer.data()))).convert("RGBA")


def main() -> None:
    QApplication.instance() or QApplication([])

    out = ROOT / "assets"
    out.mkdir(exist_ok=True)

    largest = _render(max(ICO_SIZES))
    largest.save(
        out / "icon.ico",
        sizes=[(s, s) for s in ICO_SIZES],
        append_images=[_render(s) for s in ICO_SIZES[:-1]],
    )
    print(f"생성: {out / 'icon.ico'} ({ICO_SIZES})")

    _render(max(ICNS_SIZES)).save(
        out / "icon.icns",
        append_images=[_render(s) for s in ICNS_SIZES[:-1]],
    )
    print(f"생성: {out / 'icon.icns'} ({ICNS_SIZES})")


if __name__ == "__main__":
    main()
