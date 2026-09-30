"""Versioned, guild-scoped staff-thread templates, separate from ticket records."""

import re
from copy import deepcopy
from datetime import datetime, timezone
from pymongo.errors import DuplicateKeyError

SCHEMA_VERSION = 1
MAX_SECTIONS = 25
LABELS = {
    "notice": "Private-thread notice",
    "how_heard": "How they heard about us",
    "hook": "What caught their interest",
    "donations": "Donations and clan chat",
}
NOTICE = "this is a private thread for the candidate. They cannot see this thread, so DO NOT ping them, as it will add them.\n\n"
HOOK = 'What was the hook that reeled you in? The thing that said "yeah, I need to check these guys out!!!"'
DONATIONS = "Donations are better with the update allowing loot to be used but clan chats are and can be sporadic."


def defaults(kind):
    if kind not in {"main", "fwa"}:
        raise ValueError("Choose Main or FWA.")
    body = "Hello there 👋🏻...how you hear about " + (
        "our FWA Operation?" if kind == "fwa" else "Warriors United?"
    )
    sections = {
        key: {"title": "", "body": value}
        for key, value in [("notice", NOTICE), ("how_heard", body), ("hook", HOOK)]
    }
    if kind == "fwa":
        sections["donations"] = {"title": "", "body": DONATIONS}
    return {"schema_version": SCHEMA_VERSION, "revision": 0, "sections": sections}


def validate(kind, template):
    if template.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("Unsupported staff-thread template version.")
    sections = template.get("sections", {})
    required = set(defaults(kind)["sections"])
    if (
        not isinstance(sections, dict)
        or not required <= set(sections)
        or any(
            not re.fullmatch(r"custom_[0-9a-f]{16}", key)
            for key in set(sections) - required
        )
    ):
        raise ValueError("The template has invalid sections.")
    if len(sections) > MAX_SECTIONS:
        raise ValueError(
            f"Use at most {MAX_SECTIONS} staff-thread messages per ticket type."
        )
    for section in template["sections"].values():
        if not isinstance(section, dict) or set(section) != {"title", "body"}:
            raise ValueError("Each section needs a title and body.")
        if not all(isinstance(v, str) for v in section.values()):
            raise ValueError("Section text must be text.")
        if (
            len(section["title"]) > 100
            or not section["body"].strip()
            or len(section["body"]) > 1800
        ):
            raise ValueError(
                "Use a title up to 100 characters and a body of 1–1,800 characters."
            )


async def load(mongo, guild_id, kind):
    document = await mongo.ticket_staff_templates.find_one(
        {"_id": f"{int(guild_id)}:{kind}"}
    )
    result = deepcopy(document) if document else defaults(kind)
    validate(kind, result)
    return result


async def save(mongo, guild_id, kind, template, actor_id):
    validate(kind, template)
    revision = int(template.get("revision", 0))
    key = f"{int(guild_id)}:{kind}"
    data = dict(
        schema_version=SCHEMA_VERSION,
        guild_id=int(guild_id),
        ticket_type=kind,
        sections=deepcopy(template["sections"]),
        revision=revision + 1,
        updated_by=int(actor_id),
        updated_at=datetime.now(timezone.utc),
    )
    try:
        result = await mongo.ticket_staff_templates.update_one(
            {"_id": key, "revision": revision}, {"$set": data}, upsert=revision == 0
        )
    except DuplicateKeyError:
        raise ValueError(
            "Another editor saved changes. Reopen this template before editing again."
        ) from None
    if not result.matched_count and not result.upserted_id:
        raise ValueError(
            "Another editor saved changes. Reopen this template before editing again."
        )
    return dict(data, _id=key)


def messages(kind, template=None, recruiter_role=0):
    template = template or defaults(kind)
    validate(kind, template)
    for key, section in template["sections"].items():
        if key == "notice" and not recruiter_role:
            continue
        text = (f"**{section['title']}**\n" if section["title"] else "") + section[
            "body"
        ]
        if key == "notice":
            text = f"<@&{int(recruiter_role)}> " + text
        yield key, text


def section_label(key, section):
    return LABELS.get(key) or section.get("title", "").strip() or "Additional question"
