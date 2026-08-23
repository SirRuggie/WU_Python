"""Discord-visible identifiers and structural checks for ticket intake panels."""

from __future__ import annotations

from collections.abc import Iterable


LEGACY_PANEL_ACTIONS = frozenset({"create_ticket:main", "create_ticket:fwa"})
PILOT_PANEL_ACTIONS = frozenset({
    "ticket_v2_create:pilot:main",
    "ticket_v2_create:pilot:fwa",
})


def message_action_ids(message) -> frozenset[str]:
    """Collect every nested custom ID from a Discord message."""
    found: set[str] = set()
    stack = list(getattr(message, "components", ()) or ())
    while stack:
        component = stack.pop()
        custom_id = str(getattr(component, "custom_id", "") or "")
        if custom_id:
            found.add(custom_id)
        stack.extend(getattr(component, "components", ()) or ())
    return frozenset(found)


def require_panel_actions(message, expected: Iterable[str], *, label: str) -> None:
    required = frozenset(str(value) for value in expected)
    missing = sorted(required - message_action_ids(message))
    if missing:
        raise ValueError(
            f"{label} message is missing expected controls: {', '.join(missing)}"
        )


__all__ = [
    "LEGACY_PANEL_ACTIONS",
    "PILOT_PANEL_ACTIONS",
    "message_action_ids",
    "require_panel_actions",
]
