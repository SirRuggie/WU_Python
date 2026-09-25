"""Stable title/body grouping for private management text editors.

The grouping follows the native schema, never the administrator's current copy,
so changing a heading cannot make an existing editor form change shape.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class TextEditGroup:
    key: str
    label: str
    indexes: tuple[int, ...]
    embedded_heading: bool = False


def _lines(value: str) -> list[str]:
    return [line for line in value.splitlines() if line.strip()]


def _heading_line(value: str) -> bool:
    line = value.lstrip()
    return line.startswith("#") or (line.startswith("**") and "**" in line[2:])


def _standalone_heading(value: str) -> bool:
    lines = _lines(value)
    return len(lines) == 1 and _heading_line(lines[0])


def _embedded_heading(value: str) -> bool:
    lines = _lines(value)
    return len(lines) > 1 and _heading_line(lines[0])


def groups(labels: Sequence[str], defaults: Sequence[str]) -> tuple[TextEditGroup, ...]:
    """Pair schema heading/body nodes and retain credits and normal copy alone."""
    if len(labels) != len(defaults):
        raise ValueError("Text editor labels do not match its default schema.")
    result: list[TextEditGroup] = []
    index = 0
    while index < len(defaults):
        following = index + 1
        if (
            _standalone_heading(defaults[index])
            and following < len(defaults)
            and not defaults[following].lstrip().startswith("-#")
            and not _standalone_heading(defaults[following])
            and not _embedded_heading(defaults[following])
        ):
            result.append(TextEditGroup(
                key=f"{index},{following}", label=f"{labels[index]} / {labels[following]}",
                indexes=(index, following),
            ))
            index += 2
            continue
        result.append(TextEditGroup(
            key=str(index), label=labels[index], indexes=(index,),
            embedded_heading=_embedded_heading(defaults[index]),
        ))
        index += 1
    return tuple(result)


def by_key(groups_: Sequence[TextEditGroup], key: str) -> TextEditGroup | None:
    return next((group for group in groups_ if group.key == key), None)


def legacy_single(labels: Sequence[str], defaults: Sequence[str], key: str) -> TextEditGroup | None:
    """Accept an old one-index modal id while new dropdowns use paired ids."""
    try:
        index = int(key)
    except (TypeError, ValueError):
        return None
    if index < 0 or index >= len(defaults) or len(labels) != len(defaults):
        return None
    return TextEditGroup(str(index), labels[index], (index,), _embedded_heading(defaults[index]))


def modal_fields(group: TextEditGroup, sections: Sequence[str]) -> tuple[tuple[str, str, str], ...]:
    """Return field id, label and current value for one group."""
    if len(group.indexes) == 2:
        first, second = group.indexes
        return (("title", "Title", sections[first]), ("body", "Body", sections[second]))
    value = sections[group.indexes[0]]
    if not group.embedded_heading:
        return (("text", "Text", value),)
    heading, separator, body = value.partition("\n")
    return (("title", "Title", heading), ("body", "Body", body if separator else ""))


def apply_modal(group: TextEditGroup, sections: Sequence[str], values: dict[str, str]) -> list[str]:
    """Store modal values in the original ordered schema without mutation."""
    updated = list(sections)
    if len(group.indexes) == 2:
        title, body = values.get("title", ""), values.get("body", "")
        if not title.strip() or not body.strip():
            raise ValueError("Both title and body need content.")
        updated[group.indexes[0]], updated[group.indexes[1]] = title, body
        return updated
    if group.embedded_heading:
        # A modal opened before this feature used one `text` field. Preserve
        # that in-flight interaction while new forms use title and body fields.
        if values.get("text", "").strip() and not values.get("title") and not values.get("body"):
            updated[group.indexes[0]] = values["text"]
            return updated
        title, body = values.get("title", ""), values.get("body", "")
        if not title.strip() or not body.strip():
            raise ValueError("Both title and body need content.")
        updated[group.indexes[0]] = title + "\n" + body
        return updated
    value = values.get("text", "")
    if not value.strip():
        raise ValueError("Text needs content.")
    updated[group.indexes[0]] = value
    return updated
