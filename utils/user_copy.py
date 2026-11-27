"""Shared, user-facing status and permission text."""

from __future__ import annotations

APP_NAME = "WU Wizard"
NOT_READY = "Not ready. Nothing was queued. Try again later."
QUEUED = "Queued. Waiting to start."
WAITING = "Waiting to start."
NOT_CONFIRMED = "Not confirmed. Check Discord before repeating it."
STOPPED_UNCONFIRMED = "Stopped before confirming. Check Discord before repeating it."


def needs_permissions(*names: str, where: str = "") -> str:
    """Name the application and the permissions needed for an action."""
    if not names:
        raise ValueError("Name at least one permission.")
    if len(names) == 1:
        permissions = names[0]
    elif len(names) == 2:
        permissions = " and ".join(names)
    else:
        permissions = ", ".join(names[:-1]) + ", and " + names[-1]
    location = f" {where}" if where else ""
    return f"{APP_NAME} needs {permissions}{location}."
