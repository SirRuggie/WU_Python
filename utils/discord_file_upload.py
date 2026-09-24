"""Small Hikari 2.6 compatibility layer for Discord modal file uploads.

The Hikari version used by this bot does not model Label (type 18) or File
Upload (type 19) components. Hikari can send arbitrary component builders,
but its modal deserializer intentionally drops component types it does not know.
This module preserves only submissions belonging to this feature while leaving
Hikari's normal interaction models and dispatcher unchanged.
"""

from __future__ import annotations

import copy
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

import hikari


LABEL_COMPONENT_TYPE = 18
FILE_UPLOAD_COMPONENT_TYPE = 19
_SUBMISSIONS: OrderedDict[int, tuple[float, dict[str, Any]]] = OrderedDict()
_INSTALLED = False
_MAX_SUBMISSIONS = 256
_SUBMISSION_TTL_SECONDS = 20 * 60
_UPLOAD_PREFIXES = ("content_upload_submit:", "dashboard_image_submit:", "fwa_war_footer_submit:")


@dataclass(frozen=True)
class FileUploadModalComponentBuilder:
    """Raw builder for one required file upload wrapped in a Discord Label."""

    custom_id: str
    label: str
    description: str | None = None
    file_types: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".gif", ".webp")

    def build(self) -> tuple[dict[str, Any], tuple[()]]:
        component = {
            "type": FILE_UPLOAD_COMPONENT_TYPE,
            "custom_id": self.custom_id,
            "min_values": 1,
            "max_values": 1,
            "required": True,
            "file_types": list(self.file_types),
        }
        payload: dict[str, Any] = {
            "type": LABEL_COMPONENT_TYPE,
            "label": self.label,
            "component": component,
        }
        if self.description:
            payload["description"] = self.description
        return payload, ()


def install_file_upload_capture() -> None:
    """Retain supported upload submissions before Hikari drops new fields."""

    global _INSTALLED
    if _INSTALLED:
        return
    factory = hikari.impl.EntityFactoryImpl
    original = factory.deserialize_modal_interaction

    def deserialize_modal_interaction(self, payload):
        interaction = original(self, payload)
        data = payload.get("data", {}) if isinstance(payload, dict) else {}
        data = data if isinstance(data, dict) else {}
        custom_id = data.get("custom_id", "")
        if isinstance(custom_id, str) and custom_id.startswith(_UPLOAD_PREFIXES):
            try:
                interaction_id = int(payload["id"])
            except (KeyError, TypeError, ValueError):
                pass
            else:
                resolved = data.get("resolved", {})
                resolved = resolved if isinstance(resolved, dict) else {}
                attachments = resolved.get("attachments", {})
                components = data.get("components", [])
                now = time.monotonic()
                while _SUBMISSIONS and (
                    len(_SUBMISSIONS) >= _MAX_SUBMISSIONS
                    or next(iter(_SUBMISSIONS.values()))[0] < now - _SUBMISSION_TTL_SECONDS
                ):
                    _SUBMISSIONS.popitem(last=False)
                _SUBMISSIONS[interaction_id] = (now, {
                    "custom_id": custom_id,
                    "components": copy.deepcopy(components if isinstance(components, list) else []),
                    "attachments": copy.deepcopy(attachments if isinstance(attachments, dict) else {}),
                })
        return interaction

    factory.deserialize_modal_interaction = deserialize_modal_interaction
    _INSTALLED = True


def pop_file_upload(interaction_id: int, custom_id: str, field_id: str) -> dict[str, Any] | None:
    """Return the one attachment selected for ``field_id``, or None if malformed."""

    saved = _SUBMISSIONS.pop(int(interaction_id), None)
    if not saved:
        return None
    captured_at, submission = saved
    if (
        captured_at < time.monotonic() - _SUBMISSION_TTL_SECONDS
        or submission.get("custom_id") != custom_id
    ):
        return None
    values: list[str] | None = None
    for label in submission.get("components", []):
        if not isinstance(label, dict) or label.get("type") != LABEL_COMPONENT_TYPE:
            continue
        component = label.get("component")
        if (
            isinstance(component, dict)
            and component.get("type") == FILE_UPLOAD_COMPONENT_TYPE
            and component.get("custom_id") == field_id
        ):
            raw_values = component.get("values")
            if isinstance(raw_values, list) and len(raw_values) == 1:
                values = raw_values
            break
    if values is None:
        return None
    selected_id = str(values[0])
    attachment = submission.get("attachments", {}).get(selected_id)
    if not isinstance(attachment, dict) or str(attachment.get("id")) != selected_id:
        return None
    return attachment
