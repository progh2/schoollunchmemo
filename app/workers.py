"""백그라운드 작업 실행기.

네트워크 호출은 전부 여기를 거친다. UI 스레드에서는 절대 I/O를 하지 않는다.
결과는 시그널로만 전달하고, 워커에서 위젯을 직접 건드리지 않는다.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

log = logging.getLogger(__name__)


class TaskSignals(QObject):
    ok = Signal(object)
    err = Signal(object)
    done = Signal()


class Task(QRunnable):
    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self._fn(*self._args, **self._kwargs)
        except Exception as exc:  # noqa: BLE001 - 워커에서 예외가 새면 앱이 죽는다
            log.debug("작업 실패: %s", exc, exc_info=True)
            self.signals.err.emit(exc)
        else:
            self.signals.ok.emit(result)
        finally:
            self.signals.done.emit()


# 실행 중인 작업의 참조를 붙잡아 둔다.
# 놓으면 시그널이 전달되기 전에 수거될 수 있다.
_live: set[Task] = set()


def submit(
    fn: Callable[..., Any],
    *args: Any,
    on_ok: Callable[[Any], None] | None = None,
    on_err: Callable[[Exception], None] | None = None,
    pool: QThreadPool | None = None,
    **kwargs: Any,
) -> Task:
    task = Task(fn, *args, **kwargs)
    _live.add(task)
    if on_ok is not None:
        task.signals.ok.connect(on_ok)
    if on_err is not None:
        task.signals.err.connect(on_err)
    task.signals.done.connect(lambda: _live.discard(task))
    (pool or QThreadPool.globalInstance()).start(task)
    return task
