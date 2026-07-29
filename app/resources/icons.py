"""아이콘을 코드로 그린다.

바이너리 리소스를 저장소에 두지 않아도 되고, 어떤 배포 형태에서도
파일 경로 문제가 생기지 않는다.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

from .theme import colors

_SIZES = (16, 20, 24, 32, 48, 64, 128)


def _draw_note(painter: QPainter, size: int, color: str, error: bool) -> None:
    palette = colors(color)
    pad = size * 0.09
    fold = size * 0.28
    rect = QRectF(pad, pad, size - pad * 2, size - pad * 2)

    # 오른쪽 아래 모서리가 접힌 종이 모양
    path = QPainterPath()
    path.moveTo(rect.topLeft())
    path.lineTo(rect.topRight())
    path.lineTo(QPointF(rect.right(), rect.bottom() - fold))
    path.lineTo(QPointF(rect.right() - fold, rect.bottom()))
    path.lineTo(rect.bottomLeft())
    path.closeSubpath()

    painter.setPen(QPen(QColor(palette["line"]), max(1.0, size * 0.035)))
    painter.setBrush(QBrush(QColor(palette["bg"])))
    painter.drawPath(path)

    # 접힌 부분
    fold_path = QPainterPath()
    fold_path.moveTo(QPointF(rect.right() - fold, rect.bottom()))
    fold_path.lineTo(QPointF(rect.right() - fold, rect.bottom() - fold))
    fold_path.lineTo(QPointF(rect.right(), rect.bottom() - fold))
    fold_path.closeSubpath()
    painter.setBrush(QBrush(QColor(palette["line"])))
    painter.drawPath(fold_path)

    # 글씨를 흉내 낸 선 (작은 크기에서는 생략해야 뭉개지지 않는다)
    if size >= 24:
        painter.setPen(QPen(QColor(palette["muted"]), max(1.0, size * 0.055)))
        left = rect.left() + size * 0.16
        for index in range(3):
            y = rect.top() + size * (0.28 + index * 0.18)
            right = rect.right() - size * (0.16 if index < 2 else 0.36)
            painter.drawLine(QPointF(left, y), QPointF(right, y))

    if error:
        radius = size * 0.19
        painter.setPen(QPen(QColor("#FFFFFF"), max(1.0, size * 0.045)))
        painter.setBrush(QBrush(QColor("#D93025")))
        painter.drawEllipse(
            QPointF(size - radius - pad * 0.4, size - radius - pad * 0.4),
            radius,
            radius,
        )


def note_pixmap(size: int, color: str = "yellow", error: bool = False) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    _draw_note(painter, size, color, error)
    painter.end()
    return pixmap


def app_icon(color: str = "yellow", error: bool = False) -> QIcon:
    icon = QIcon()
    for size in _SIZES:
        icon.addPixmap(note_pixmap(size, color, error))
    return icon
