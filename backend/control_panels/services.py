"""Public service layer for control panels (ADR-0094).

This module exposes panel-control primitives that rule action handlers
import without crossing into the Z-Wave JS integration layer directly,
preserving the import-boundary invariant from ADR-0091.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from django.db import transaction

from control_panels.models import (
    ControlPanelDevice,
    ControlPanelIntegrationType,
    ControlPanelKind,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class ControlPanelNotFound(Exception):
    """Raised when a panel_id does not match an enabled ``ControlPanelDevice``."""


def _load_panel(panel_id: int) -> ControlPanelDevice:
    try:
        return ControlPanelDevice.objects.select_for_update().get(id=panel_id, enabled=True)
    except ControlPanelDevice.DoesNotExist as exc:
        raise ControlPanelNotFound(f"Control panel id={panel_id} not found or disabled") from exc


def _dispatch_write_after_commit(panel_id: int, state: str, countdown_seconds: int | None) -> None:
    """Schedule the indicator write to run after the current transaction commits.

    The flag flip on ``follow_alarm_state`` must hit the DB before the keypad
    write so that any interleaved ``alarm_state_change_committed`` receiver
    sees the new flag and skips the auto-sync for this panel.
    """

    def _do_write() -> None:
        # Imported lazily so this module never pulls Z-Wave JS at import time.
        from control_panels.zwave_ring_keypad_v2 import apply_ring_keypad_v2_panel_state

        try:
            device = ControlPanelDevice.objects.get(id=panel_id, enabled=True)
        except ControlPanelDevice.DoesNotExist:
            return
        if device.integration_type != ControlPanelIntegrationType.ZWAVEJS:
            return
        if device.kind != ControlPanelKind.RING_KEYPAD_V2:
            return
        try:
            apply_ring_keypad_v2_panel_state(device=device, state=state, countdown_seconds=countdown_seconds)
        except Exception:
            logger.warning(
                "control_panels: indicator write failed for panel %s state=%s",
                panel_id,
                state,
                exc_info=True,
            )

    transaction.on_commit(_do_write)


@transaction.atomic
def apply_panel_state(
    *,
    panel_id: int,
    state: str,
    countdown_seconds: int | None = None,
) -> ControlPanelDevice:
    """Set a control panel into an explicit indicator state (ADR-0094).

    Flips ``follow_alarm_state=False`` so the keypad won't be re-synced from
    the central alarm state. Returns the updated device row.
    """
    device = _load_panel(panel_id)
    if device.follow_alarm_state:
        device.follow_alarm_state = False
        device.save(update_fields=["follow_alarm_state", "updated_at"])
    _dispatch_write_after_commit(panel_id=device.id, state=state, countdown_seconds=countdown_seconds)
    return device


@transaction.atomic
def trigger_panel(*, panel_id: int) -> ControlPanelDevice:
    """Light a control panel's burglar indicator (ADR-0094).

    Equivalent to ``apply_panel_state(state="triggered")`` but exposed as
    a separate primitive for rule-author clarity.
    """
    return apply_panel_state(panel_id=panel_id, state="triggered")


@transaction.atomic
def resume_auto(*, panel_id: int) -> ControlPanelDevice:
    """Re-enable auto-mirror on a control panel and immediately re-sync.

    Called by ``control_panel_set_state(state="auto")``. The sync runs
    after commit so the flag flip is visible to the sync's queryset.
    """
    device = _load_panel(panel_id)
    if not device.follow_alarm_state:
        device.follow_alarm_state = True
        device.save(update_fields=["follow_alarm_state", "updated_at"])

    def _resync() -> None:
        from control_panels.zwave_ring_keypad_v2 import sync_ring_keypad_v2_devices_state

        try:
            sync_ring_keypad_v2_devices_state()
        except Exception:
            logger.warning("control_panels: resume_auto sync failed", exc_info=True)

    transaction.on_commit(_resync)
    return device


def resume_auto_all_on_disarm() -> int:
    """Flip every panel back to ``follow_alarm_state=True``.

    Called from the merged ``alarm_state_change_committed`` receiver when
    the alarm transitions to DISARMED, so rule-controlled panels rejoin
    the auto-mirror without operator intervention.
    """
    return ControlPanelDevice.objects.filter(follow_alarm_state=False).update(follow_alarm_state=True)
