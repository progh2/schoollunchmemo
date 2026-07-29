"""NEIS 교육정보 개방 포털 Open API 클라이언트."""

from .client import NeisClient, NeisError
from .codes import ResultKind, classify, user_message
from .models import Dish, MealMenu, ScheduleEvent, School

__all__ = [
    "NeisClient",
    "NeisError",
    "ResultKind",
    "classify",
    "user_message",
    "Dish",
    "MealMenu",
    "ScheduleEvent",
    "School",
]
