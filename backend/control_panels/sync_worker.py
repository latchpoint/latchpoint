"""
Panel-sync worker (ADR-0100): the single owner of all control-panel Indicator CC writes.

Supervised Z-Wave writes to a keypad block for up to 10 s each. Before ADR-0100 they ran inline
in `alarm_state_change_committed` receivers — on the HTTP request thread (app arm/disarm), the
single `zwavejs-events` thread (keypad-initiated transitions, starving the panel's own inbound
events), or the scheduler thread. This worker moves every panel write onto one dedicated thread:

- Callers enqueue work and return immediately (`request_sync`, `request_siren_reassert`,
  `request_code_rejected`).
- Sync requests are coalesced: a burst of state changes reconciles once, against the LATEST
  alarm snapshot.
- Writes to a device are serialized (one thread), diffed against the device's
  `last_written_indicators`, and retried a bounded number of times on failure.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

_SYNC_MAX_ATTEMPTS = 3
_SYNC_RETRY_BACKOFF_SECONDS = 1.0


class PanelSyncWorker:
    def __init__(self) -> None:
        self._cond = threading.Condition()
        self._generation = 0
        self._synced_generation = 0
        self._force_siren_edge = False
        self._one_shots: deque[tuple[str, int]] = deque()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Start the worker thread (idempotent)."""
        with self._cond:
            if self._thread is not None and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._run, name="panel-sync", daemon=True)
            self._thread.start()

    def request_sync(self) -> None:
        """Ask for a reconcile against the latest alarm snapshot; returns immediately."""
        with self._cond:
            self._generation += 1
            self._cond.notify()

    def request_siren_reassert(self) -> None:
        """Ask for a reconcile that re-sounds the burglar siren via a value-changing write."""
        with self._cond:
            self._generation += 1
            self._force_siren_edge = True
            self._cond.notify()

    def request_code_rejected(self, *, device_id: int) -> None:
        """Queue the "code not accepted" tone/LED for a device; returns immediately."""
        with self._cond:
            self._one_shots.append(("code_rejected", device_id))
            self._cond.notify()

    # -- worker internals ---------------------------------------------------

    def _has_work(self) -> bool:
        return bool(self._one_shots) or self._synced_generation != self._generation

    def _run(self) -> None:  # pragma: no cover - exercised via _drain in tests
        while True:
            with self._cond:
                while not self._has_work():
                    self._cond.wait()
            try:
                self._drain()
            except Exception:
                logger.exception("Panel sync worker: drain failed")

    def _drain(self) -> None:
        """Process queued one-shots, then reconcile to the latest state, until idle."""
        from control_panels.zwave_ring_keypad_v2 import _maybe_close_old_connections

        _maybe_close_old_connections()
        while True:
            with self._cond:
                one_shots = list(self._one_shots)
                self._one_shots.clear()
                generation = self._generation
                force_siren_edge = self._force_siren_edge
                self._force_siren_edge = False
            for kind, device_id in one_shots:
                try:
                    self._play_one_shot(kind=kind, device_id=device_id)
                except Exception:
                    logger.warning("Panel sync worker: one-shot %s failed device_id=%s", kind, device_id, exc_info=True)
            if generation != self._synced_generation:
                self._reconcile(generation=generation, force_siren_edge=force_siren_edge)
            with self._cond:
                if not self._has_work():
                    return

    def _reconcile(self, *, generation: int, force_siren_edge: bool) -> None:
        from control_panels.zwave_ring_keypad_v2 import sync_ring_keypad_v2_devices_state

        self._synced_generation = generation
        for attempt in range(1, _SYNC_MAX_ATTEMPTS + 1):
            failed_devices = sync_ring_keypad_v2_devices_state(force_siren_edge=force_siren_edge)
            if failed_devices == 0:
                return
            with self._cond:
                if self._generation != generation:
                    # A newer state was requested meanwhile; reconcile against that instead.
                    return
            if attempt < _SYNC_MAX_ATTEMPTS:
                logger.warning(
                    "Panel sync: %s device(s) failed, retrying (attempt %s/%s)",
                    failed_devices,
                    attempt,
                    _SYNC_MAX_ATTEMPTS,
                )
                time.sleep(_SYNC_RETRY_BACKOFF_SECONDS)
        logger.warning("Panel sync: giving up after %s attempts (next state change retries)", _SYNC_MAX_ATTEMPTS)

    def _play_one_shot(self, *, kind: str, device_id: int) -> None:
        from control_panels.models import ControlPanelDevice
        from control_panels.zwave_ring_keypad_v2 import play_code_rejected

        try:
            device = ControlPanelDevice.objects.get(id=device_id)
        except ControlPanelDevice.DoesNotExist:
            return
        if kind == "code_rejected":
            play_code_rejected(device=device)


panel_sync_worker = PanelSyncWorker()
