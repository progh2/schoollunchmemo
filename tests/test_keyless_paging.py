"""인증키 없는 NEIS의 5건 제한을 나눠 부르기로 넘는지 (#38).

실제 NEIS처럼 요청마다 조건에 맞는 row 중 앞의 5건만 주고, 머리에 전체
건수(list_total_count)를 싣는 가짜 서버로 확인한다.
"""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlparse

import pytest

from app.neis.client import SEARCH_LIMIT, NeisClient
from app.neis.models import School

CAP = 5  # 인증키 없는 요청이 받는 최대 row 수

SCHOOL = School(
    office_code="B10",
    office_name="서울특별시교육청",
    school_code="7011569",
    school_name="미림마이스터고등학교",
)


class _Response:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


class FakeNeis:
    """조건으로 거른 뒤 앞의 CAP건만 주는 서버. pSize·pIndex는 무시한다."""

    def __init__(self, data: dict[str, list[dict]]):
        self.data = data
        self.calls: list[dict] = []

    def get(self, url, params=None, timeout=None):
        service = urlparse(url).path.rsplit("/", 1)[-1]
        params = dict(params or {})
        self.calls.append({"service": service, **params})
        rows = [row for row in self.data.get(service, []) if self._match(row, params)]
        if not rows:
            return _Response(
                {"RESULT": {"CODE": "INFO-200", "MESSAGE": "해당하는 데이터가 없습니다."}}
            )
        head = [{"list_total_count": len(rows)}, {"RESULT": {"CODE": "INFO-000"}}]
        return _Response({service: [{"head": head}, {"row": rows[:CAP]}]})

    @staticmethod
    def _match(row: dict, params: dict) -> bool:
        for key, value in params.items():
            if key in ("Type", "pIndex", "pSize"):
                continue
            if key == "SCHUL_NM":
                if value not in row["SCHUL_NM"]:
                    return False
            elif key.endswith("_FROM_YMD"):
                if row[key.replace("_FROM_YMD", "_YMD")] < value:
                    return False
            elif key.endswith("_TO_YMD"):
                if row[key.replace("_TO_YMD", "_YMD")] > value:
                    return False
            elif row.get(key) != value:
                return False
        return True


def _client(fake: FakeNeis) -> NeisClient:
    client = NeisClient()
    client._session = fake
    return client


def _school_days(year: int, month: int) -> list[date]:
    day = date(year, month, 1)
    days = []
    while day.month == month:
        if day.weekday() < 5:
            days.append(day)
        day += timedelta(days=1)
    return days


def _meal_rows(days: list[date], codes=("1", "2", "3")) -> list[dict]:
    return [
        {
            "ATPT_OFCDC_SC_CODE": "B10",
            "SD_SCHUL_CODE": "7011569",
            "MLSV_YMD": f"{day:%Y%m%d}",
            "MMEAL_SC_CODE": code,
            "MMEAL_SC_NM": {"1": "조식", "2": "중식", "3": "석식"}[code],
            "DDISH_NM": f"{day.day}일밥",
        }
        for day in days
        for code in codes
    ]


def _event_rows(days: list[date]) -> list[dict]:
    return [
        {
            "ATPT_OFCDC_SC_CODE": "B10",
            "SD_SCHUL_CODE": "7011569",
            "AA_YMD": f"{day:%Y%m%d}",
            "EVENT_NM": f"{day.day}일 행사",
        }
        for day in days
    ]


class TestMonth:
    def test_whole_month_arrives_despite_cap(self):
        days = _school_days(2026, 9)  # 평일 22일
        meals = _meal_rows(days)  # 66행
        events = _event_rows(days[::2])  # 11건
        fake = FakeNeis({"mealServiceDietInfo": meals, "SchoolSchedule": events})

        meal_rows, schedule_rows = _client(fake).fetch_month_rows(SCHOOL, 2026, 9)

        assert len(meal_rows) == len(meals)
        assert {(r["MLSV_YMD"], r["MMEAL_SC_CODE"]) for r in meal_rows} == {
            (r["MLSV_YMD"], r["MMEAL_SC_CODE"]) for r in meals
        }
        assert len(schedule_rows) == len(events)
        # 한 달에 이 정도면 하루 1000건 한도와 거리가 멀다
        assert len(fake.calls) < 40

    def test_small_month_is_one_call_each(self):
        days = _school_days(2026, 9)[:4]
        fake = FakeNeis(
            {
                "mealServiceDietInfo": _meal_rows(days, codes=("2",)),
                "SchoolSchedule": _event_rows(days[:2]),
            }
        )
        meal_rows, schedule_rows = _client(fake).fetch_month_rows(SCHOOL, 2026, 9)
        assert (len(meal_rows), len(schedule_rows)) == (4, 2)
        assert len(fake.calls) == 2  # 잘리지 않았으면 나눠 부르지 않는다

    def test_busy_single_day_does_not_loop_forever(self):
        """하루치도 5건을 넘으면 더 나눌 수 없다. 받은 만큼 쓰고 끝낸다."""
        day = date(2026, 9, 15)
        events = [
            {**_event_rows([day])[0], "EVENT_NM": f"행사{i}"} for i in range(8)
        ]
        fake = FakeNeis({"mealServiceDietInfo": [], "SchoolSchedule": events})
        _, schedule_rows = _client(fake).fetch_month_rows(SCHOOL, 2026, 9)
        assert len(schedule_rows) == CAP
        assert len(fake.calls) < 20


def _school_row(name: str, office: str, code: str, kind="고등학교", fond="공립") -> dict:
    return {
        "ATPT_OFCDC_SC_CODE": office,
        "ATPT_OFCDC_SC_NM": f"{office}교육청",
        "SD_SCHUL_CODE": code,
        "SCHUL_NM": name,
        "SCHUL_KND_SC_NM": kind,
        "FOND_SC_NM": fond,
    }


class TestSearch:
    def test_few_results_is_one_call(self):
        fake = FakeNeis(
            {"schoolInfo": [_school_row("미림마이스터고등학교", "B10", "7011569")]}
        )
        result = _client(fake).search_schools("미림")
        assert [s.school_name for s in result] == ["미림마이스터고등학교"]
        assert len(fake.calls) == 1

    def test_split_by_office_and_kind_finds_all(self):
        rows = [
            _school_row(f"과학고{i}", office, f"{office}{i}", kind=kind)
            for i, (office, kind) in enumerate(
                [("B10", "고등학교")] * 4
                + [("J10", "고등학교")] * 4
                + [("J10", "중학교")] * 3
                + [("C10", "고등학교")] * 2
            )
        ]
        fake = FakeNeis({"schoolInfo": rows})
        result = _client(fake).search_schools("과학")
        assert len(result) == len(rows) == result.total
        assert len({(s.office_code, s.school_code) for s in result}) == len(rows)

    def test_too_common_name_is_not_split(self):
        rows = [
            _school_row(f"서울학교{i}", "B10", f"S{i}") for i in range(SEARCH_LIMIT + 1)
        ]
        fake = FakeNeis({"schoolInfo": rows})
        result = _client(fake).search_schools("서울")
        assert len(result) == CAP
        assert result.total == SEARCH_LIMIT + 1
        assert len(fake.calls) == 1

    def test_empty_name(self):
        fake = FakeNeis({})
        assert list(_client(fake).search_schools("  ")) == []
        assert fake.calls == []


@pytest.mark.parametrize("shown, total, expected", [(3, 3, "3개를 찾았습니다"), (5, 650, "전체 650개 중 5개")])
def test_dialog_tells_when_results_are_partial(qapp, shown, total, expected):
    from app.config import Config
    from app.neis.client import SearchResult
    from app.neis.models import School as SchoolModel
    from app.settings_dialog import SettingsDialog

    schools = SearchResult(
        [
            SchoolModel(office_code="B10", office_name="서울", school_code=str(i), school_name=f"학교{i}")
            for i in range(shown)
        ],
        total=total,
    )
    dialog = SettingsDialog(Config())
    try:
        dialog._on_search_done(schools)
        assert expected in dialog.search_status.text()
        assert dialog.result_list.count() == shown
    finally:
        dialog.deleteLater()
