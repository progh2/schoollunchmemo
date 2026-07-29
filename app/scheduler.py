"""날짜 롤오버 감지.

자정까지 남은 시간을 계산해 한 번만 깨우고, 그와 별개로 1분 간격 확인을
둔다. 절전에서 복귀했거나 시스템 시계가 바뀌면 단발 타이머가 제때 울리지
않기 때문이다.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger(__name__)

GUARD_INTERVAL_MS = 60_000
MIDNIGHT_MARGIN_MS = 2_000


class DayScheduler(QObject):
    dayChanged = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._current_day = date.today()

        self._midnight_timer = QTimer(self)
        self._midnight_timer.setSingleShot(True)
        self._midnight_timer.timeout.connect(self._check)

        self._guard_timer = QTimer(self)
        self._guard_timer.setInterval(GUARD_INTERVAL_MS)
        self._guard_timer.timeout.connect(self._check)

    def start(self) -> None:
        self._current_day = date.today()
        self._arm_midnight()
        self._guard_timer.start()

    def stop(self) -> None:
        self._midnight_timer.stop()
        self._guard_timer.stop()

    @property
    def current_day(self) -> date:
        return self._current_day

    def _arm_midnight(self) -> None:
        now = datetime.now()
        next_midnight = datetime.combine(now.date() + timedelta(days=1), time.min)
        msecs = int((next_midnight - now).total_seconds() * 1000) + MIDNIGHT_MARGIN_MS
        self._midnight_timer.start(max(1000, msecs))

    def _check(self) -> None:
        today = date.today()
        if today != self._current_day:
            log.info("날짜가 %s → %s 로 바뀌었습니다.", self._current_day, today)
            self._current_day = today
            self.dayChanged.emit()
        self._arm_midnight()
