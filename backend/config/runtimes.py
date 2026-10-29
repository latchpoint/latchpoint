"""
Decide whether this process starts the long-running runtimes (#160).

The apps start their runtimes from `AppConfig.ready()`: the MQTT connection, the Z-Wave JS client, the HA
state stream and MQTT alarm entity, the control panel listener and sync worker, and the scheduler.
`ready()` runs in every process that loads Django, management commands included, so they check
`should_start_runtimes()` first and only start in the server process.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence

from django.conf import settings

logger = logging.getLogger(__name__)

# Servers that run the app, matched on argv[0]. They take their own flags as argv[1] (`daphne -b ...`), so
# argv[1] isn't a management command for them. The match is on the exact executable name, so a renamed
# launcher (ie `gunicorn3`) isn't detected and needs START_RUNTIMES=true.
_SERVER_PROGRAMS = frozenset({"daphne", "uvicorn", "gunicorn"})

_FORCE_ON = frozenset({"1", "true", "yes", "on"})
_FORCE_OFF = frozenset({"0", "false", "no", "off"})
_AUTO = frozenset({"", "auto"})


def should_start_runtimes(argv: Sequence[str]) -> bool:
    """
    Return True if this process should start the long-running runtimes.

    `START_RUNTIMES` decides if it's set to a true or false value. Otherwise (unset or "auto"), only a
    server process starts them: daphne, uvicorn or gunicorn, or `manage.py runserver`. Management commands
    and test runners don't.

    `argv` is passed in rather than read here, so each app's `ready()` passes its own module's `sys.argv`
    and a test can stand in a server's argv for just that app.
    """
    override = _override()
    if override is not None:
        return override
    return is_server_argv(argv)


def is_server_argv(argv: Sequence[str]) -> bool:
    """Return True if `argv` is a process that serves the app."""
    if not argv:
        return False
    if _program_name(argv[0]) in _SERVER_PROGRAMS:
        return True
    if len(argv) > 1 and argv[1] == "runserver":
        # With the autoreloader on, the process that was started only watches files. It serves from a child
        # it starts with RUN_MAIN=true, so only that child counts.
        return "--noreload" in argv or os.environ.get("RUN_MAIN") == "true"
    return False


def _program_name(arg0: str) -> str:
    name = os.path.basename(arg0 or "")
    if name == "__main__.py":
        # `python -m daphne` runs `.../daphne/__main__.py`.
        return os.path.basename(os.path.dirname(arg0))
    return name


def _override() -> bool | None:
    raw = str(getattr(settings, "START_RUNTIMES", "") or "").strip().lower()
    if raw in _AUTO:
        return None
    if raw in _FORCE_ON:
        return True
    if raw in _FORCE_OFF:
        return False
    logger.warning("START_RUNTIMES=%r isn't true, false or auto, so it's treated as auto", raw)
    return None
