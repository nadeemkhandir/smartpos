"""
Running blocking work off the UI thread.

Two things in the sign-in path take real time: PBKDF2, which is slow *on
purpose*, and SMTP, which waits on a server that may be having a bad day. Doing
either on the Qt thread freezes the window, so both go through :class:`Task`.

    task = Task(auth_service.login, username, password, remember=True)
    task.succeeded.connect(self._on_signed_in)     # runs on the UI thread
    task.failed.connect(self._on_error)
    run(task)

The signals are delivered back on the UI thread by Qt's queued connections, so
handlers may touch widgets freely.

Lifetime matters more than it looks. The worker thread finishes long before the
UI thread gets round to the queued signals it emitted, so a task that drops its
last reference at the end of ``run()`` takes its signal object down with it and
those pending signals are silently discarded — the sign-in button would stick on
"Signing in...". Every task is therefore held in ``_in_flight`` until a slot
running *on the UI thread* releases it, which by then is after the handlers have
had their turn.
"""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot

from app.core.logger import get_logger

logger = get_logger(__name__)

#: Tasks currently in flight, held so Python does not collect them early.
_in_flight: set["Task"] = set()


class _Signals(QObject):
    """QRunnable is not a QObject, so its signals live on this companion."""

    succeeded = Signal(object)
    failed = Signal(Exception)
    finished = Signal()


class Task(QRunnable):
    """One call to ``function(*args, **kwargs)`` on a background thread."""

    def __init__(self, function: Callable[..., Any], *args: Any, **kwargs: Any):
        super().__init__()

        self.function = function
        self.args = args
        self.kwargs = kwargs

        self._signals = _Signals()
        self.succeeded = self._signals.succeeded
        self.failed = self._signals.failed
        self.finished = self._signals.finished

        # The thread pool must not delete this the moment run() returns: its
        # signals still have to reach the UI thread. Released by run() below.
        self.setAutoDelete(False)

    @Slot()
    def run(self) -> None:
        try:
            result = self.function(*self.args, **self.kwargs)
        except Exception as error:  # noqa: BLE001 - reported to the caller instead
            # Anything the service raises belongs on screen, not in a traceback
            # on a shop-floor terminal, so every exception is forwarded.
            logger.exception("Background task %s failed", getattr(self.function, "__name__", "?"))
            self._signals.failed.emit(error)
        else:
            self._signals.succeeded.emit(result)
        finally:
            self._signals.finished.emit()


def run(task: Task, pool: QThreadPool | None = None) -> Task:
    """Start ``task``, holding a reference to it until its last signal lands.

    The release is connected after whatever the caller connected, and Qt calls
    slots in connection order, so the task outlives every handler that needed it.
    """
    _in_flight.add(task)
    task.finished.connect(lambda: _in_flight.discard(task))

    (pool or QThreadPool.globalInstance()).start(task)
    return task


def run_async(
    function: Callable[..., Any],
    *args: Any,
    on_success: Callable[[Any], None] | None = None,
    on_error: Callable[[Exception], None] | None = None,
    on_finished: Callable[[], None] | None = None,
    **kwargs: Any,
) -> Task:
    """Shorthand for building a :class:`Task`, connecting it and starting it."""
    task = Task(function, *args, **kwargs)

    if on_success:
        task.succeeded.connect(on_success)
    if on_error:
        task.failed.connect(on_error)
    if on_finished:
        task.finished.connect(on_finished)

    return run(task)
