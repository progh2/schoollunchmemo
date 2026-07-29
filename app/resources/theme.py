"""포스트잇 색상 팔레트.

배경과 본문 글자의 대비를 4.5:1 이상으로 잡는다 (NFR-07).
"""

from __future__ import annotations

PALETTE: dict[str, dict[str, str]] = {
    "yellow": {
        "bg": "#FFEDA6",
        "bg_bottom": "#FFE07A",
        "line": "#E6CE7C",
        "text": "#3A3122",
        "muted": "#7A6B4A",
        "accent": "#A8431A",
    },
    "pink": {
        "bg": "#FFD9E2",
        "bg_bottom": "#FFC3D2",
        "line": "#EDB9C6",
        "text": "#3D2530",
        "muted": "#7C5566",
        "accent": "#A8264C",
    },
    "sky": {
        "bg": "#D5EBFF",
        "bg_bottom": "#BEDDFA",
        "line": "#B0CFE8",
        "text": "#1F2E3D",
        "muted": "#4E6577",
        "accent": "#14568C",
    },
    "mint": {
        "bg": "#D8F2DD",
        "bg_bottom": "#C1E8CA",
        "line": "#AED8B7",
        "text": "#223326",
        "muted": "#4F6B56",
        "accent": "#1C6B3A",
    },
}

DEFAULT_COLOR = "yellow"


def colors(name: str | None = None) -> dict[str, str]:
    return PALETTE.get(name or DEFAULT_COLOR, PALETTE[DEFAULT_COLOR])
