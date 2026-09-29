"""NEIS Open API HTTP 클라이언트.

인증키 없이 공개 API를 호출한다 (일 1000건 제한).
모든 호출은 워커 스레드에서 실행되는 것을 전제로 한다 (내부에서 sleep 한다).

인증키가 없으면 NEIS는 요청 하나에 **최대 5건**만 돌려준다(샘플 모드).
pSize·pIndex를 무시하므로 페이지를 넘길 수도 없다. 그래서 응답 머리의
전체 건수(list_total_count)보다 적게 받았으면, 조건을 잘게 나눠 다시 부른다
(#38). 5건 이하인 조회는 지금처럼 한 번에 끝난다.
"""

from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from typing import Any

import requests

from .codes import ResultKind, user_message
from .models import MEAL_TYPES, MealMenu, ScheduleEvent, School
from .parser import parse_meals, parse_schedule, parse_schools, total_count, unwrap

log = logging.getLogger(__name__)

BASE_URL = "https://open.neis.go.kr/hub"
CONNECT_TIMEOUT = 5.0
READ_TIMEOUT = 10.0
BACKOFF_SECONDS = (2, 8, 30)
MAX_ATTEMPTS = 3
SEARCH_LIMIT = 100
#: 한 달치는 급식 최대 93행, 일정도 100행을 넘지 않는다. 한 번에 다 받는다.
MONTH_PAGE_SIZE = 1000

#: 나눠 부를 때 동시에 보내는 요청 수. 서버에 무리를 주지 않을 만큼만.
PARALLEL_REQUESTS = 4

#: 학교 검색을 나눠 부를 때 쓰는 시도교육청 코드 (재외한국학교 포함 18곳)
OFFICE_CODES = (
    "B10", "C10", "D10", "E10", "F10", "G10", "H10", "I10", "J10",
    "K10", "M10", "N10", "P10", "Q10", "R10", "S10", "T10", "V10",
)

SERVICE_SCHOOL_INFO = "schoolInfo"
SERVICE_MEAL = "mealServiceDietInfo"
SERVICE_SCHEDULE = "SchoolSchedule"


#: 학교 검색을 학교급으로 나눌 때 쓰는 이름 (NEIS SCHUL_KND_SC_NM 값)
SCHOOL_KINDS = (
    "초등학교", "중학교", "고등학교", "특수학교", "각종학교",
    "고등공민학교", "고등기술학교", "방송통신중학교", "방송통신고등학교",
)


#: 학교 검색이 잘렸을 때 차례로 나눌 기준 (NEIS schoolInfo 요청 인자)
SEARCH_SPLITS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("ATPT_OFCDC_SC_CODE", OFFICE_CODES),
    ("SCHUL_KND_SC_NM", SCHOOL_KINDS),
    ("FOND_SC_NM", ("국립", "공립", "사립")),
)  # NEIS가 요청 인자로 받는 것만 쓴다. 모르는 인자는 무시돼 같은 결과가 온다.


class SearchResult(list):
    """학교 검색 결과. total은 NEIS가 알려 준 전체 건수다."""

    def __init__(self, items=(), total: int | None = None) -> None:
        super().__init__(items)
        self.total = len(self) if total is None else total


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
        return self._request_page(service, params)[0]

    def _request_page(
        self, service: str, params: dict[str, Any]
    ) -> tuple[list[dict], int | None]:
        """row 목록과 전체 건수. 전체 건수보다 row가 적으면 잘린 것이다."""
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
                return rows, total_count(payload, service)
            if kind is ResultKind.SERVER:
                last_error = NeisError(kind, code, message)
                continue
            # 인증키·요청 오류·한도 초과는 재시도해도 달라지지 않는다
            raise NeisError(kind, code, message)

        raise last_error or NeisError(ResultKind.UNKNOWN)

    # ------------------------------------------------------------ 나눠 부르기

    @staticmethod
    def _truncated(rows: list[dict], total: int | None) -> bool:
        return total is not None and len(rows) < total

    def _fan_out(self, service: str, variants: list[dict[str, Any]]) -> list[dict]:
        """조건만 다른 요청 여럿을 몇 개씩 동시에 보내고 결과를 잇는다."""
        with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
            chunks = list(pool.map(lambda p: self._request(service, p), variants))
        return [row for chunk in chunks for row in chunk]

    def _collect_range(
        self,
        service: str,
        params: dict[str, Any],
        keys: tuple[str, str],
        first: date,
        last: date,
    ) -> list[dict]:
        """기간 조회를 잘리지 않을 만큼 잘게 나눠 모두 받는다.

        먼저 기간 전체를 한 번 부른다. 잘렸으면 전체 건수로 한 번에 담길
        기간 길이를 어림해 그 길이로 나누고, 조각마다 같은 일을 되풀이한다.
        하루치도 잘리면 더 나눌 수 없으니 받은 만큼만 쓴다.
        """
        from_key, to_key = keys
        span = {from_key: f"{first:%Y%m%d}", to_key: f"{last:%Y%m%d}"}
        rows, total = self._request_page(service, {**params, **span})
        if not self._truncated(rows, total):
            return rows
        days = (last - first).days + 1
        if days == 1:
            log.info("%s %s: 하루치가 %s건을 넘어 일부만 받았습니다.", service, first, len(rows))
            return rows

        step = max(1, min(days // 2, days * len(rows) // max(total or 1, 1)))
        windows = []
        start = first
        while start <= last:
            end = min(last, start + timedelta(days=step - 1))
            windows.append((start, end))
            start = end + timedelta(days=1)
        with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
            chunks = list(
                pool.map(
                    lambda w: self._collect_range(service, params, keys, *w), windows
                )
            )
        return [row for chunk in chunks for row in chunk]

    def _split_search(
        self, params: dict[str, Any], splits: tuple[tuple[str, tuple[str, ...]], ...]
    ) -> list[dict]:
        """학교 검색을 기준 하나씩 더 나눠 부른다. 잘린 조각만 더 들어간다."""
        key, values = splits[0]
        rest = splits[1:]

        def one(value: str) -> list[dict]:
            scoped = {**params, key: value}
            part, part_total = self._request_page(SERVICE_SCHOOL_INFO, scoped)
            if self._truncated(part, part_total) and rest:
                return self._split_search(scoped, rest)
            return part

        with ThreadPoolExecutor(max_workers=PARALLEL_REQUESTS) as pool:
            return [row for part in pool.map(one, values) for row in part]

    # ------------------------------------------------------------ 고수준

    def search_schools(self, name: str) -> "SearchResult":
        """이름으로 학교를 찾는다.

        5건을 넘으면 시도교육청별로, 그래도 넘으면 학교급별로 나눠 부른다.
        결과가 SEARCH_LIMIT을 넘을 만큼 흔한 이름이면 나눠 부르지 않는다.
        수백 번 부를 일이고, 그렇게 많으면 어차피 골라 볼 수 없다.
        """
        name = (name or "").strip()
        if not name:
            return SearchResult()
        base = {"SCHUL_NM": name}
        rows, total = self._request_page(SERVICE_SCHOOL_INFO, base)
        if self._truncated(rows, total) and (total or 0) <= SEARCH_LIMIT:
            rows = self._split_search(base, SEARCH_SPLITS)
            # 나눈 조각끼리 겹칠 수 있으니 학교 코드로 한 번 거른다
            unique: dict[tuple[str, str], dict] = {}
            for row in rows:
                key = (str(row.get("ATPT_OFCDC_SC_CODE")), str(row.get("SD_SCHUL_CODE")))
                unique.setdefault(key, row)
            rows = list(unique.values())
        return SearchResult(parse_schools(rows), total=total or len(rows))

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

    def fetch_month_rows(
        self, school: School, year: int, month: int
    ) -> tuple[list[dict], list[dict]]:
        """한 달치 급식·학사일정 원본 row. 달력에 표시를 찍는 데 쓴다.

        급식 구분으로 걸러 받지 않는다. 달력은 어느 급식이 있는지를 보여주는
        것이 목적이므로 세 구분을 다 받아 두고, 표시할 때 설정으로 고른다.
        """
        first = date(year, month, 1)
        last = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)
        school_params = {
            "ATPT_OFCDC_SC_CODE": school.office_code,
            "SD_SCHUL_CODE": school.school_code,
            "pSize": MONTH_PAGE_SIZE,
        }
        meal_keys = ("MLSV_FROM_YMD", "MLSV_TO_YMD")

        # 급식은 하루에 세 번까지라 날짜로만 나누면 조각이 하루 단위로 잘게
        # 쪼개진다. 잘렸으면 끼니별로 먼저 나눠(하루 한 건) 호출 수를 줄인다.
        meal_rows, meal_total = self._request_page(
            SERVICE_MEAL,
            {
                **school_params,
                meal_keys[0]: f"{first:%Y%m%d}",
                meal_keys[1]: f"{last:%Y%m%d}",
            },
        )
        if self._truncated(meal_rows, meal_total):
            meal_rows = [
                row
                for code in MEAL_TYPES.values()
                for row in self._collect_range(
                    SERVICE_MEAL,
                    {**school_params, "MMEAL_SC_CODE": code},
                    meal_keys,
                    first,
                    last,
                )
            ]

        schedule_rows = self._collect_range(
            SERVICE_SCHEDULE,
            school_params,
            ("AA_FROM_YMD", "AA_TO_YMD"),
            first,
            last,
        )
        return meal_rows, schedule_rows

    @staticmethod
    def meals_from_rows(rows: list[dict]) -> list[MealMenu]:
        return parse_meals(rows)

    @staticmethod
    def schedule_from_rows(rows: list[dict]) -> list[ScheduleEvent]:
        return parse_schedule(rows)
