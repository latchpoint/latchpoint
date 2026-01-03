from __future__ import annotations


def normalize_contact_state(raw_state: str | None) -> str:
    """
    Normalize raw entity state to a UI-friendly contact state.

    Returns: "open" | "closed" | "unknown"
    """

    state = (raw_state or "").strip().lower()
    if not state or state in {"unknown", "unavailable", "none", "null"}:
        return "unknown"
    if state in {"on", "open", "opened", "true", "1"}:
        return "open"
    if state in {"off", "closed", "false", "0"}:
        return "closed"
    return "unknown"

