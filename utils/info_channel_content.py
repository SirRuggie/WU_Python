"""Read-only clan selection and text composition for native info channels.

Template persistence remains owned by the existing content editor. These
functions never save templates, resolve destinations, or send Discord messages.
"""

import re
from collections.abc import Mapping, Sequence

from pymongo.errors import PyMongoError

from utils.constants import CLAN_TYPES as REGISTRY_CLAN_TYPES
from utils.info_channel_defaults import ABOUT_US_COPY, FAMILY_RULES, WU_FAQ_QUESTIONS, WU_FAQ_NEW_FIELDS


CLAN_TYPES = tuple(kind for kind in REGISTRY_CLAN_TYPES if kind in {"Tactical", "Flexible Fun", "FWA"})
TEXT_LIMIT = 4000
_TAG = re.compile(r"#[0289PYLQGRJCUV]{3,16}\Z")
_MANUAL_CLAN_LINE = re.compile(
    r"^\*\*[^\n]+?(?:\s+\(#[A-Za-z0-9]+\)\*\*|\*\*\s+`#[A-Za-z0-9]+`)\s*$"
)
_COUNT_LINE = re.compile(r"^(?:🛡️?|:shield:)\s+(\d+)\s+(.+)$")
_MARKDOWN = re.compile(r"([\\`*_{}\[\]()<>~|])")


class InfoContentUnavailable(ValueError):
    """An actionable render failure; callers must not send a fallback post."""


def strip_manual_clan_prefix(body: str) -> str:
    """Remove only consecutive leading old name/tag lines, never stored data."""
    lines = body.splitlines(keepends=True)
    while lines and _MANUAL_CLAN_LINE.fullmatch(lines[0].rstrip("\r\n")):
        lines.pop(0)
    return "".join(lines)


def strip_manual_clan_suffix(body: str) -> str:
    lines = body.splitlines(keepends=True)
    while lines and _MANUAL_CLAN_LINE.fullmatch(lines[-1].rstrip("\r\n")):
        lines.pop()
    return "".join(lines).rstrip("\n")


def about_us_defaults() -> list[str]:
    fields = list(ABOUT_US_COPY)
    for index in (3, 5, 7):
        fields[index] = strip_manual_clan_prefix(fields[index])
    return fields


def wu_faq_sections(sections: Sequence[str] | None = None) -> list[str]:
    """Append missing new fields; never rewrite saved Questions or storage."""
    defaults = [*WU_FAQ_QUESTIONS, *WU_FAQ_NEW_FIELDS]
    if sections is not None and not isinstance(sections, (list, tuple)):
        raise ValueError("WU FAQ needs all 9 text fields. Reopen the editor.")
    fields = list(defaults if sections is None else sections)
    if 2 <= len(fields) < len(defaults):
        fields.extend(defaults[len(fields):])
    validate_fields(fields, 9, "WU FAQ")
    return fields


def clan_lines(groups: Mapping[str, Sequence[Mapping[str, str]]], kind: str) -> str:
    """The shared registry-name escaping used by About Us and WU FAQ."""
    if set(groups) != set(CLAN_TYPES) or any(not groups[item] for item in CLAN_TYPES):
        raise InfoContentUnavailable("The clan registry is incomplete. Preview again after checking all three clan types.")
    lines = []
    for clan in groups[kind]:
        name = _MARKDOWN.sub(r"\\\1", clan["name"])
        lines.append(f"**{name}** `{clan['tag']}`")
    return "\n".join(lines)


def family_rules_sections(sections: Sequence[str] | None = None) -> list[str]:
    if sections is not None and not isinstance(sections, (list, tuple)):
        raise ValueError("Family Rules needs a heading and body list. Reopen the editor.")
    fields = list(FAMILY_RULES if sections is None else sections)
    validate_fields(fields, 2, "Family Rules")
    return fields


def validate_fields(fields: Sequence[str], expected: int, label: str) -> None:
    if (not isinstance(fields, (list, tuple)) or len(fields) != expected
            or any(not isinstance(value, str) or not value.strip() for value in fields)):
        raise ValueError(f"{label} needs all {expected} text fields. Reopen the editor.")


async def load_family_clans(mongo, *, include_cwl=False, require_nonempty=True) -> dict[str, list[dict[str, str]]]:
    """Fetch a single consistent list for both the displayed lines and counts."""
    kinds = (*CLAN_TYPES, "CWL") if include_cwl else CLAN_TYPES
    query = {
        "type": {"$in": list(kinds)},
        "archived": {"$ne": True},
        "removed": {"$ne": True},
    }
    try:
        rows = await mongo.clans.find(query).to_list(length=None)
    except (PyMongoError, OSError, TimeoutError) as error:
        raise InfoContentUnavailable(
            "I cannot read the clan registry right now. No post was changed. "
            "Try Preview again when the registry is available."
        ) from error
    if not isinstance(rows, list):
        raise InfoContentUnavailable("The clan registry response is incomplete. Check the registry, then Preview again.")
    groups = {kind: [] for kind in kinds}
    tags = set()
    for row in rows:
        if not isinstance(row, Mapping):
            raise InfoContentUnavailable("The clan registry has an invalid entry. Check the registry, then Preview again.")
        kind = row.get("type")
        if (kind not in kinds or row.get("archived") is True
                or row.get("removed") is True):
            continue
        name, tag = row.get("name"), row.get("tag")
        if (not isinstance(name, str) or not name.strip() or "\n" in name or "\r" in name
                or not isinstance(tag, str) or not _TAG.fullmatch(tag.upper())):
            raise InfoContentUnavailable(
                "An active clan needs a valid name and tag. Correct the clan registry, then Preview again."
            )
        tag = tag.upper()
        if tag in tags:
            raise InfoContentUnavailable("The clan registry has a duplicate active clan. Correct it before posting.")
        tags.add(tag)
        entry = {"name": name, "tag": tag}
        if include_cwl:
            entry["emoji"] = row.get("emoji", "")
        groups[kind].append(entry)
    for clans in groups.values():
        clans.sort(key=lambda clan: (clan["name"].casefold(), clan["tag"]))
    if require_nonempty and any(not clans for clans in groups.values()):
        raise InfoContentUnavailable(
            "An active clan list is empty. Check all three clan types in the registry before posting."
        )
    return groups


def _count_kind(description: str) -> str | None:
    lowered = description.casefold()
    if "tactical" in lowered and "clan" in lowered:
        return "Tactical"
    if "flexible fun" in lowered and "clan" in lowered:
        return "Flexible Fun"
    if "fwa" in lowered and "clan" in lowered:
        return "FWA"
    return None


def _overview_counts(body: str, groups: Mapping[str, Sequence]) -> str:
    lines = body.splitlines(keepends=True)
    found = set()
    for index, line in enumerate(lines):
        match = _COUNT_LINE.fullmatch(line.rstrip("\r\n"))
        kind = _count_kind(match[2]) if match else None
        if kind is None:
            continue
        count = len(groups[kind])
        start, end = match.span(1)
        rendered = line[:start] + str(count) + line[end:]
        rendered = re.sub(
            r"\b([Cc])lans?\b",
            lambda noun: noun[1] + ("lan" if count == 1 else "lans"),
            rendered,
        )
        lines[index] = rendered
        found.add(kind)
    # A custom description can omit the default count lines. Keep its wording
    # and append only the missing derived counts rather than inventing zeroes.
    missing = [kind for kind in CLAN_TYPES if kind not in found]
    if missing:
        labels = {"Tactical": "tactical clans", "Flexible Fun": "Flexible Fun war clans", "FWA": "FWA clans for farmers"}
        derived = "\n".join(
            f"🛡️ {len(groups[kind])} " + (
                labels[kind].replace("clans", "clan") if len(groups[kind]) == 1 else labels[kind]
            ) for kind in missing
        )
        return "".join(lines) + "\n\n**What we offer:**\n" + derived
    return "".join(lines)


def about_us_sections(fields: Sequence[str], groups: Mapping[str, Sequence[Mapping[str, str]]]) -> list[str]:
    """Derive public text without modifying the twelve stored editor fields."""
    validate_fields(fields, len(fields) if len(fields) in {12,16} else 12, "About Us")
    if set(groups) != set(CLAN_TYPES) or any(not groups[kind] for kind in CLAN_TYPES):
        raise InfoContentUnavailable("The clan registry is incomplete. Preview again after checking all three clan types.")
    rendered = list(fields)
    rendered[1] = _overview_counts(fields[1], groups)
    for index, kind in ((3, "Tactical"), (5, "Flexible Fun"), (7, "FWA")):
        rendered[index] = clan_lines(groups, kind) + "\n" + strip_manual_clan_prefix(fields[index])
    return rendered


def validate_rendered_text(texts: Sequence[str]) -> int:
    total = sum(len(text) for text in texts)
    if total > TEXT_LIMIT:
        raise ValueError(
            f"This rendered post has {total:,} characters; the limit is 4,000. "
            "No post was changed. Edit its text or review the clan registry, then Preview again."
        )
    return total
