"""
In-memory ring-buffer log handler that captures entries for the Debug > Logs tab
and broadcasts WARNING+ entries over WebSocket.

Inspired by Home Assistant's ``system_log`` component but simplified:
- No deduplication — every entry is visible for full trace-ability
- No rate limiting — bounded deque (default 500) is self-limiting
- No QueueHandler pipeline — ``deque`` + ``threading.Lock`` is sufficient

Broadcasts are decoupled from ``emit()`` via a background worker thread to avoid
deadlocking Daphne's event loop — ``async_to_sync`` cannot safely be called from
within a logging handler because ``emit()`` may fire from any thread context
(sync view threads, the async event loop, or ``sync_to_async`` worker threads).
"""

from __future__ import annotations

import itertools
import logging
import queue
import threading
import traceback
from collections import deque
from datetime import datetime, timezone
from typing import Any

# ---------------------------------------------------------------------------
# ANSI color codes per log level
# ---------------------------------------------------------------------------
_LEVEL_ANSI: dict[int, str] = {
    logging.DEBUG: "\033[90m",     # Gray (bright black)
    logging.INFO: "\033[36m",      # Cyan
    logging.WARNING: "\033[33m",   # Yellow
    logging.ERROR: "\033[31m",     # Red
    logging.CRITICAL: "\033[1;31m",  # Bold red
}
_ANSI_RESET = "\033[0m"
_ANSI_CYAN = "\033[36m"
_ANSI_DIM = "\033[2m"

_sequence = itertools.count(1)

# ---------------------------------------------------------------------------
# Module-level buffer + lock (singleton pattern)
# ---------------------------------------------------------------------------
_buffer: deque[dict[str, Any]] = deque(maxlen=500)
_lock = threading.Lock()
_broadcast_level = logging.WARNING
_capture_level = logging.DEBUG


def configure(
    *,
    buffer_size: int = 500,
    capture_level: int = logging.DEBUG,
    broadcast_level: int = logging.WARNING,
) -> None:
    """(Re)configure module-level buffer settings. Called once from AppConfig.ready()."""
    global _buffer, _broadcast_level, _capture_level

    _capture_level = capture_level
    _broadcast_level = broadcast_level

    with _lock:
        old_entries = list(_buffer)
        _buffer = deque(old_entries, maxlen=buffer_size)


def get_buffered_entries(
    *,
    level: int | None = None,
    logger_name: str | None = None,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Return buffered log entries, optionally filtered."""
    with _lock:
        entries = list(_buffer)

    if level is not None:
        entries = [e for e in entries if e["level_no"] >= level]
    if logger_name is not None:
        entries = [e for e in entries if logger_name in e["logger"]]
    if limit is not None:
        entries = entries[-limit:]

    return entries


def clear_buffer() -> None:
    """Clear the in-memory ring buffer."""
    with _lock:
        _buffer.clear()


# ---------------------------------------------------------------------------
# ANSI formatting
# ---------------------------------------------------------------------------

def _format_ansi(entry: dict[str, Any]) -> str:
    """Build a pre-formatted ANSI string for direct xterm.js rendering."""
    level_no = entry["level_no"]
    color = _LEVEL_ANSI.get(level_no, "")
    level_name = entry["level"].ljust(8)

    # Timestamp: dim gray
    ts = entry["timestamp"]
    if isinstance(ts, str):
        # Extract HH:MM:SS from ISO timestamp
        time_part = ts[11:19] if len(ts) >= 19 else ts
    else:
        time_part = ts.strftime("%H:%M:%S")

    line = f"{_ANSI_DIM}{time_part}{_ANSI_RESET} {color}{level_name}{_ANSI_RESET} {_ANSI_DIM}{entry['logger']}{_ANSI_RESET}"
    line += f"\n  {color}{entry['message']}{_ANSI_RESET}"

    # Stack trace: same level color with cyan file paths
    if entry.get("exc_text"):
        for tb_line in entry["exc_text"].splitlines():
            stripped = tb_line.strip()
            if stripped.startswith("File "):
                line += f"\n  {_ANSI_CYAN}{tb_line}{_ANSI_RESET}"
            else:
                line += f"\n  {color}{tb_line}{_ANSI_RESET}"

    return line


# ---------------------------------------------------------------------------
# WebSocket broadcast via background worker thread
# ---------------------------------------------------------------------------
# ``emit()`` can fire from any thread context: sync Django views (thread pool
# workers spawned by ``sync_to_async``), the Daphne/asyncio event loop thread,
# or standalone threads.  Calling ``async_to_sync`` from a ``sync_to_async``
# worker thread schedules the coroutine on the main event loop and *blocks*
# waiting for the result — but if the event loop is busy the request thread
# hangs, stalling all HTTP responses.
#
# To avoid this, we push entries onto a ``queue.SimpleQueue`` (non-blocking,
# thread-safe, no GIL-release needed) and let a single daemon worker thread
# drain the queue and call ``async_to_sync`` from a clean context that has no
# parent event-loop association.
# ---------------------------------------------------------------------------

_broadcast_queue: queue.SimpleQueue[dict[str, Any]] = queue.SimpleQueue()


def _broadcast_worker() -> None:
    """Drain the broadcast queue and send entries to the Channels group.

    Runs in a daemon thread started at module import time so it is always
    available — even before ``AppConfig.ready()`` fires.
    """
    from asgiref.sync import async_to_sync
    from channels.layers import get_channel_layer

    while True:
        entry = _broadcast_queue.get()
        try:
            channel_layer = get_channel_layer()
            if channel_layer is None:
                continue

            message = {
                "type": "log_entry",
                "timestamp": entry["timestamp"],
                "sequence": next(_sequence),
                "payload": entry,
            }
            async_to_sync(channel_layer.group_send)(
                "alarm",
                {"type": "broadcast", "message": message},
            )
        except Exception:
            # Best-effort — never let broadcast failures crash the worker.
            pass


_broadcast_thread = threading.Thread(target=_broadcast_worker, daemon=True)
_broadcast_thread.start()


def _enqueue_broadcast(entry: dict[str, Any]) -> None:
    """Enqueue a log entry for WebSocket broadcast (non-blocking)."""
    try:
        _broadcast_queue.put_nowait(entry)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# The handler
# ---------------------------------------------------------------------------

class BufferedWebSocketHandler(logging.Handler):
    """
    Logging handler that appends structured entries to an in-memory ring buffer
    and broadcasts WARNING+ entries over WebSocket.

    Each entry contains both structured JSON fields and a pre-formatted ANSI
    string for direct xterm.js rendering.
    """

    def emit(self, record: logging.LogRecord) -> None:
        if record.levelno < _capture_level:
            return

        try:
            entry = self._build_entry(record)

            with _lock:
                _buffer.append(entry)

            if record.levelno >= _broadcast_level:
                _enqueue_broadcast(entry)

        except Exception:
            self.handleError(record)

    @staticmethod
    def _build_entry(record: logging.LogRecord) -> dict[str, Any]:
        exc_text = None
        if record.exc_info and record.exc_info[1] is not None:
            exc_text = "".join(traceback.format_exception(*record.exc_info))

        timestamp = datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat()

        entry: dict[str, Any] = {
            "timestamp": timestamp,
            "level": record.levelname,
            "level_no": record.levelno,
            "logger": record.name,
            "message": record.getMessage(),
            "exc_text": exc_text,
            "filename": record.filename,
            "lineno": record.lineno,
            "func_name": record.funcName,
        }
        entry["formatted"] = _format_ansi(entry)
        return entry
