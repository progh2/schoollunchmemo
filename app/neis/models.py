"""NEIS 응답을 앱에서 쓰는 형태로 정규화한 모델."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

MEAL_TYPES: dict[str, str] = {"breakfast": "1", "lunch": "2", "dinner": "3"}
MEAL_TYPE_LABELS: dict[str, str] = {
    "breakfast": "조식",
    "lunch": "중식",
    "dinner": "석식",
}
MEAL_CODE_TO_KEY: dict[str, str] = {v: k for k, v in MEAL_TYPES.items()}


@dataclass(frozen=True)
class School:
    office_code: str  # ATPT_OFCDC_SC_CODE
    office_name: str  # ATPT_OFCDC_SC_NM
    school_code: str  # SD_SCHUL_CODE
    school_name: str  # SCHUL_NM
    school_kind: str = ""  # SCHUL_KND_SC_NM
    location: str = ""  # LCTN_SC_NM
    address: str = ""  # ORG_RDNMA

    @property
    def subtitle(self) -> str:
        """목록에서 동명이교를 구분하기 위한 보조 설명."""
        parts = [p for p in (self.office_name, self.address or self.location) if p]
        return " · ".join(parts)

    def to_config(self) -> dict[str, str]:
        return {
            "office_code": self.office_code,
            "office_name": self.office_name,
            "school_code": self.school_code,
            "school_name": self.school_name,
            "school_kind": self.school_kind,
        }

    @classmethod
    def from_config(cls, data: dict) -> School:
        return cls(
            office_code=data.get("office_code", ""),
            office_name=data.get("office_name", ""),
            school_code=data.get("school_code", ""),
            school_name=data.get("school_name", ""),
            school_kind=data.get("school_kind", ""),
        )


@dataclass(frozen=True)
class Dish:
    name: str
    allergens: tuple[str, ...] = ()

    def display(self, show_allergens: bool = False) -> str:
        if show_allergens and self.allergens:
            return f"{self.name} ({'.'.join(self.allergens)})"
        return self.name


@dataclass(frozen=True)
class MealMenu:
    day: date
    meal_key: str  # breakfast | lunch | dinner
    meal_name: str  # 조식 | 중식 | 석식
    dishes: tuple[Dish, ...] = ()
    calorie: float | None = None
    origin: str = ""
    nutrition: str = ""

    @property
    def label(self) -> str:
        return self.meal_name or MEAL_TYPE_LABELS.get(self.meal_key, "급식")


@dataclass(frozen=True)
class ScheduleEvent:
    day: date
    name: str
    content: str = ""
    is_holiday: bool = False
    grades: frozenset[int] = field(default_factory=frozenset)

    def applies_to(self, grade: int | None) -> bool:
        """학년 필터. 학년 정보가 없는 일정은 항상 표시한다."""
        if grade is None or not self.grades:
            return True
        return grade in self.grades

    @property
    def grade_label(self) -> str:
        if not self.grades or len(self.grades) >= 6:
            return ""
        return "·".join(f"{g}" for g in sorted(self.grades)) + "학년"
