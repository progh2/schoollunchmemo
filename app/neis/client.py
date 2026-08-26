"""NEIS Open API HTTP 클라이언트.

인증키 없이 공개 API를 호출한다 (일 1000건 제한).
모든 호출은 워커 스레드에서 실행되는 것을 전제로 한다 (내부에서 sleep 한다).
"""

from __future__ import annotations

import logging
import time
from datetime import date
from typing import Any

import requests

from .codes import ResultKind, user_message
from .models import MEAL_TYPES, MealMenu, ScheduleEvent, School
from .parser import parse_meals, parse_schedule, parse_schools, unwrap

log = logging.getLogger(__name__)

BASE_URL = "https://open.neis.go.kr/hub"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
BACKOFF_SECONDS = (2, 8, 30)
MAX_ATTEMPTS = 3
SEARCH_LIMIT = 100

SERVICE_SCHOOL_INFO = "schoolInfo"
SERVICE_MEAL = "mealServiceDietInfo"
SERVICE_SCHEDULE = "SchoolSchedule"


class NeisError(Exception):
    """NEIS 호출 실패. kind로 사용자 안내 문구를 결정한다."""

    def __init__(self, kind: ResultKind, code: str = "", message: str = "") -> None:
        self.kind = kind
        self.code = code
        self.raw_message = message
        super().__init__(user_message(kind, code, message))

    @property
    def user_text(self) -> str:
        return str(self)


class NeisClient:
    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "SchoolNote/0.1 (+desktop widget)"

    # ------------------------------------------------------------ 저수준

    def _request(self, service: str, params: dict[str, Any]) -> list[dict]:
        query: dict[str, Any] = {"Type": "json", "pIndex": 1, "pSize": 100, **params}
        url = f"{BASE_URL}/{service}"

        last_error: NeisError | None = None
        for attempt in range(MAX_ATTEMPTS):
            if attempt:
                time.sleep(BACKOFF_SECONDS[min(attempt - 1, len(BACKOFF_SECONDS) - 1)])
            try:
                log.debug("GET %s %s", url, query)
                response = self._session.get(
                    url, params=query, timeout=(CONNECT_TIMEOUT, READ_TIMEOUT)
                )
            except requests.RequestException as exc:
                log.info("네트워크 오류 (%s/%s): %s", attempt + 1, MAX_ATTEMPTS, exc)
                last_error = NeisError(ResultKind.NETWORK, message=str(exc))
                continue

            if response.status_code >= 500:
                last_error = NeisError(
                    ResultKind.SERVER, code=str(response.status_code)
                )
                continue

            try:
                payload = response.json()
            except ValueError:
                # 점검 페이지 등 JSON이 아닌 응답
                last_error = NeisError(
                    ResultKind.SERVER, message="JSON이 아닌 응답을 받았습니다."
                )
                continue

            kind, code, message, rows = unwrap(payload, service)
            if kind in (ResultKind.OK, ResultKind.NO_DATA):
                return rows
            if kind is ResultKind.SERVER:
                last_error = NeisError(kind, code, message)
                continue
            # 인증키·요청 오류·한도 초과는 재시도해도 달라지지 않는다
            raise NeisError(kind, code, message)

        raise last_error or NeisError(ResultKind.UNKNOWN)

    # ------------------------------------------------------------ 고수준

    def search_schools(self, name: str) -> list[School]:
        name = (name or "").strip()
        if not name:
            return []
        rows = self._request(
            SERVICE_SCHOOL_INFO, {"SCHUL_NM": name, "pSize": SEARCH_LIMIT}
        )
        return parse_schools(rows)

    def fetch_meal_rows(
        self, school: School, day: date, meal_keys: list[str] | None = None
    ) -> list[dict]:
        params: dict[str, Any] = {
            "ATPT_OFCDC_SC_CODE": school.office_code,
            "SD_SCHUL_CODE": school.school_code,
            "MLSV_YMD": f"{day:%Y%m%d}",
        }
        # 구분이 하나뿐일 때만 서버에서 거른다. 여러 개면 전부 받아 앱에서 고른다.
        if meal_keys and len(meal_keys) == 1:
            code = MEAL_TYPES.get(meal_keys[0])
            if code:
                params["MMEAL_SC_CODE"] = code
        return self._request(SERVICE_MEAL, params)

    def fetch_schedule_rows(self, school: School, day: date) -> list[dict]:
        return self._request(
            SERVICE_SCHEDULE,
            {
                "ATPT_OFCDC_SC_CODE": school.office_code,
                "SD_SCHUL_CODE": school.school_code,
                "AA_YMD": f"{day:%Y%m%d}",
            },
        )

    def fetch_day(
        self, school: School, day: date, meal_keys: list[str] | None = None
    ) -> tuple[list[dict], list[dict]]:
        """급식·학사일정 원본 row를 함께 가져온다. 캐시에 그대로 저장한다."""
        meal_rows = self.fetch_meal_rows(school, day, meal_keys)
        schedule_rows = self.fetch_schedule_rows(school, day)
        return meal_rows, schedule_rows

    @staticmethod
    def meals_from_rows(rows: list[dict]) -> list[MealMenu]:
        return parse_meals(rows)

    @staticmethod
    def schedule_from_rows(rows: list[dict]) -> list[ScheduleEvent]:
        return parse_schedule(rows)
