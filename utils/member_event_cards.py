"""Pure Discord card payloads shared by gateway delivery and dashboard previews."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from utils.member_events import GUILD_ID, safe_text

EVENT_STYLE = {
    "join": ("👋", "Member joined", "joined", 0x2BA66A),
    "leave": ("🚪", "Member left", "left", 0xD34A4A),
    "kick": ("👢", "Member kicked", "was kicked", 0xE69935),
    "ban": ("🔨", "Member banned", "was banned", 0xA8384B),
    "timeout_add": ("⏳", "Member timed out", "was timed out", 0xD8B13A),
    "timeout_remove": ("✅", "Timeout removed", "had a timeout removed", 0x4C9BE8),
    "member_update": ("✏️", "Profile changed", "updated their profile", 0x6B7FD7),
    "link": ("🔗", "Link posted", "posted a link", 0x8A8F98),
    "invite_create": ("✉️", "Invite created", "created", 0x2BA6A6),
    "invite_delete": ("🗑️", "Invite deleted", "deleted", 0x7A7F87),
    "invite_use": ("📨", "Invite used", "joined using", 0x3FA34D),
}
EXTRA_KINDS = ("timeout_add", "timeout_remove", "member_update", "link",
               "invite_create", "invite_delete", "invite_use")
USER_KINDS = ("timeout_add", "timeout_remove", "member_update", "link", "invite_use")
FIELD_LABELS = {"nickname": "Nickname", "username": "Username", "global_name": "Display name",
                "avatar": "Avatar", "guild_avatar": "Server avatar", "discriminator": "Discriminator"}
DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"
CDN_PREFIX = "https://cdn.discordapp.com/"


def accent(kind: str) -> int:
    return EVENT_STYLE[kind][3]


def avatar_filename(row: dict) -> str | None:
    if not row.get("avatar"):
        return None
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/gif": "gif",
                 "image/webp": "webp"}[row["avatar_type"]]
    return f"member-avatar.{extension}"


def _stamp(value: object) -> int | None:
    if not isinstance(value, datetime):
        return None
    return int(value.replace(tzinfo=value.tzinfo or timezone.utc).timestamp())


def _date(value: object) -> str:
    stamp = _stamp(value)
    return f"<t:{stamp}:f> · <t:{stamp}:R>" if stamp is not None else "Date unavailable"


def _moment(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _duration(seconds: object) -> str:
    total = int(seconds) if isinstance(seconds, (int, float)) and seconds > 0 else 0
    parts = []
    for size, unit in ((86400, "d"), (3600, "h"), (60, "m")):
        if total >= size:
            parts.append(f"{total // size}{unit}")
            total %= size
    return " ".join(parts) or "Unavailable"


def _since(joined: object, now: object) -> str:
    start, end = _moment(joined), _moment(now)
    if not start or not end:
        return "Unavailable"
    days = (end.replace(tzinfo=end.tzinfo or timezone.utc)
            - start.replace(tzinfo=start.tzinfo or timezone.utc)).days
    if days < 1:
        return "Less than a day"
    years, months = days // 365, (days % 365) // 30
    if years:
        return f"{years}y {months}mo" if months else f"{years}y"
    return f"{months}mo {days % 30}d" if months else f"{days}d"


def _snowflake(value: object) -> str | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return str(number) if number > 0 else None


def _roles(row: dict) -> str:
    roles = row.get("roles")
    if roles is None:
        return "Unavailable"
    if not isinstance(roles, (list, tuple)):
        return "Unavailable"
    names = [safe_text(name, 80) for name in roles]
    names = [name for name in names if name]
    if not names:
        return "None"
    return ", ".join(names[:15]) + (f" +{len(names) - 15} more" if len(names) > 15 else "")


def _inert(value: object, limit: int) -> str:
    """Escaped text whose http(s) links Discord will not turn into anchors."""
    return re.sub(r"(?i)\b(https?)://", "\\1\u200b://", safe_text(value, limit))


def _code(value: object) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "", str(value or ""))[:32] or "unknown"


def _mention(prefix: str, value: object, fallback: object = None) -> str:
    number = _snowflake(value)
    if number:
        return f"<{prefix}{number}>"
    return safe_text(fallback, 60) or "Unknown"


def _extra_content(row: dict, test_staff_id: object = None) -> tuple[list[str], str | None]:
    kind = row["event_type"]
    icon, title, action, _ = EVENT_STYLE[kind]
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    uid = _snowflake(row.get("user_id")) if kind in USER_KINDS else None
    if kind in USER_KINDS and uid is None:
        raise ValueError("A trusted member ID is required for a profile card")
    name = safe_text(row.get("display_name")) or ("Unknown member" if uid else "Unknown invite")
    moderator = _snowflake(row.get("moderator_id"))
    by = f" by <@{moderator}>" if moderator else " by an unknown moderator"
    reason = f"**Reason**\n{safe_text(row.get('reason'), 500) or 'No reason given'}"
    served = f"**Time in server**\n{_since(row.get('joined_at'), row.get('occurred_at'))}"
    fields: list[str] = []
    main = f"<@{uid}> {action}" if uid else ""
    if kind == "timeout_add":
        main += by
        fields = [reason, f"**Duration**\n{_duration(details.get('duration_seconds'))}",
                  f"**Expires**\n{_date(_moment(details.get('until')))}", served]
    elif kind == "timeout_remove":
        main += by
        fields = [reason, served]
    elif kind == "member_update":
        for change in (details.get("changes") or [])[:6]:
            label = FIELD_LABELS.get(change.get("field"))
            if not label:
                continue
            if change.get("field") in ("avatar", "guild_avatar"):
                fields.append(f"**{label}**\nChanged")
            else:
                before = safe_text(change.get("before"), 100) or "None"
                after = safe_text(change.get("after"), 100) or "None"
                fields.append(f"**{label}**\n{before} → {after}")
        actor = _snowflake(details.get("actor_id"))
        if actor:
            fields.append(f"**Changed by**\n<@{actor}>")
    elif kind == "link":
        channel = _snowflake(details.get("channel_id"))
        if channel:
            main += f" in <#{channel}>"
        fields.append(f"**Message**\n{_inert(details.get('content'), 500) or 'No text'}")
        urls = [str(url).replace("`", "")[:200] for url in (details.get("urls") or [])[:10]]
        if urls:
            fields.append("**Links**\n" + "\n".join(f"`{url}`" for url in urls))
    else:
        code = "Vanity URL" if details.get("vanity") else f"`{_code(details.get('code'))}`"
        invite_name = safe_text(details.get("name"), 40)
        inviter = _mention("@", details.get("inviter_id"), details.get("inviter_name"))
        channel = _mention("#", details.get("channel_id"), details.get("channel_name"))
        limit = details.get("max_uses")
        limit_text = f"{int(limit):,}" if isinstance(limit, int) and limit > 0 else "Unlimited"
        if kind == "invite_use":
            if details.get("unknown"):
                code = "Unknown invite"
            main += f" {code}"
            fields.append(f"**Invite**\n{code}")
            if invite_name:
                fields.append(f"**Name**\n{invite_name}")
            if not details.get("unknown"):
                if details.get("inviter_id") or details.get("inviter_name"):
                    fields.append(f"**Inviter**\n{inviter}")
                fields.append(f"**Uses**\n{int(details.get('uses') or 0):,} of {limit_text}")
        else:
            main = f"Invite {code} was {action}"
            if kind == "invite_create" and (details.get("inviter_id") or details.get("inviter_name")):
                main += f" by {inviter}"
            if invite_name:
                fields.append(f"**Name**\n{invite_name}")
            if kind == "invite_create":
                expires = _moment(details.get("expires_at"))
                fields += [f"**Channel**\n{channel}", f"**Max uses**\n{limit_text}",
                           f"**Expires**\n{_date(expires) if expires else 'Never'}"]
            else:
                fields += [f"**Channel**\n{channel}",
                           f"**Uses at deletion**\n{int(details.get('uses') or 0):,}"]
    occurred = _stamp(row.get("occurred_at"))
    footer = (f"ID {uid} · " if uid else "") + (f"<t:{occurred}:f>" if occurred is not None else "Date unavailable")
    staff = _snowflake(test_staff_id)
    if test_staff_id is not None:
        footer += f" · Test log · sent by <@{staff}>" if staff else " · Test log · staff unavailable"
    return [name, f"### {icon} {title}", main, *fields, footer], uid


def _content(row: dict, test_staff_id: object = None) -> tuple[list[str], str | None]:
    kind = row["event_type"]
    if kind in EXTRA_KINDS:
        return _extra_content(row, test_staff_id)
    icon, title, action, _ = EVENT_STYLE[kind]
    uid = _snowflake(row.get("user_id"))
    if uid is None:
        raise ValueError("A trusted member ID is required for a profile card")
    name = safe_text(row.get("display_name")) or "Unknown member"
    moderator = _snowflake(row.get("moderator_id"))
    main = f"<@{uid}> {action}"
    if kind in ("kick", "ban"):
        main += f" by <@{moderator}>" if moderator else " by an unknown moderator"
    fields = []
    if kind == "join":
        fields.append(f"**Account created**\n{_date(row.get('account_created_at'))}")
        count = row.get("member_count")
        members = f"{count:,}" if isinstance(count, int) and count >= 0 else "unavailable"
        fields.append(f"**Members**\n{members}")
    else:
        fields.append(f"**Joined**\n{_date(row.get('joined_at'))}")
        fields.append(f"**Roles**\n{_roles(row)}")
        if kind in ("kick", "ban"):
            fields.insert(0, f"**Reason**\n{safe_text(row.get('reason'), 500) or 'No reason given'}")
        count = row.get("member_count")
        members = f"{count:,}" if isinstance(count, int) and count >= 0 else "unavailable"
    occurred = _stamp(row.get("occurred_at"))
    when = f"<t:{occurred}:f>" if occurred is not None else "Date unavailable"
    footer = f"Members: {members} · ID {uid} · {when}"
    staff = _snowflake(test_staff_id)
    if test_staff_id is not None:
        footer += f" · Test log · sent by <@{staff}>" if staff else " · Test log · staff unavailable"
    return [name, f"### {icon} {title}", main, *fields, footer], uid


def _avatar_url(row: dict) -> str | None:
    filename = avatar_filename(row)
    if filename:
        return f"attachment://{filename}"
    if row["event_type"] in EXTRA_KINDS:  # New logs never store avatar bytes.
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        url = str(details.get("avatar_url") or "")
        if url.startswith(CDN_PREFIX):
            return url
        return DEFAULT_AVATAR if row["event_type"] in USER_KINDS else None
    return DEFAULT_AVATAR


def _buttons(row: dict, uid: str | None) -> list[dict]:
    buttons = [_profile_button(uid)] if uid else []
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    channel, message = _snowflake(details.get("channel_id")), _snowflake(details.get("message_id"))
    if row["event_type"] == "link" and channel and message:
        buttons.append({"type": 2, "style": 5, "label": "Jump to message ↗",
                        "url": f"https://discord.com/channels/{GUILD_ID}/{channel}/{message}"})
    return buttons


def _profile_button(uid: str) -> dict:
    return {"type": 2, "style": 5, "label": "View profile ↗",
            "url": f"https://discord.com/users/{uid}"}


def build_card(row: dict, test_staff_id: object = None) -> dict:
    """Components V2 message for text channels and existing forum-post replies."""
    lines, uid = _content(row, test_staff_id)
    name, title, main, *rest = lines
    footer = rest.pop()
    avatar = _avatar_url(row)
    header = ({"type": 9, "components": [{"type": 10, "content": f"**{name}**"}],
               "accessory": {"type": 11, "media": {"url": avatar},
                             "description": "Member avatar"}} if avatar
              else {"type": 10, "content": f"**{name}**"})
    buttons = _buttons(row, uid)
    children = [
        header,
        {"type": 10, "content": title},
        {"type": 10, "content": main},
        *({"type": 10, "content": field} for field in rest),
        {"type": 14, "divider": True, "spacing": 1},
        {"type": 10, "content": footer},
        *([{"type": 1, "components": buttons}] if buttons else []),
    ]
    return {"flags": 1 << 15, "components": [
        {"type": 17, "accent_color": accent(row["event_type"]), "components": children}
    ], "allowed_mentions": {"parse": []}}


def build_forum_message(row: dict, test_staff_id: object = None) -> dict:
    """Forum starters cannot set the V2 flag; retain one embed-based starter."""
    lines, uid = _content(row, test_staff_id)
    name, title, main, *rest = lines
    description = "\n\n".join([f"**{name}**", title, main, *rest])
    avatar = _avatar_url(row)
    buttons = _buttons(row, uid)
    return {
        "embeds": [{"description": description, "color": accent(row["event_type"]),
                    **({"thumbnail": {"url": avatar}} if avatar else {})}],
        **({"components": [{"type": 1, "components": buttons}]} if buttons else {}),
        "allowed_mentions": {"parse": []},
    }


SAMPLE_DETAILS = {
    "timeout_add": {"until": "2026-10-30T18:00:00+00:00", "duration_seconds": 86400},
    "member_update": {"changes": [{"field": "nickname", "before": "Sample", "after": "Sample member"},
                                  {"field": "avatar", "before": None, "after": None}],
                      "actor_id": "987654321098765432"},
    "link": {"channel_id": "223456789012345678", "message_id": "323456789012345678",
             "content": "Have you seen https://example.com/clan-guide yet?",
             "urls": ["https://example.com/clan-guide"]},
    "invite_create": {"code": "sampleCode", "name": "Spring recruitment", "inviter_id": "987654321098765432",
                      "channel_id": "223456789012345678", "max_uses": 10,
                      "expires_at": "2026-11-05T18:00:00+00:00"},
    "invite_delete": {"code": "sampleCode", "name": "Spring recruitment",
                      "channel_id": "223456789012345678", "uses": 7},
    "invite_use": {"code": "sampleCode", "name": "Spring recruitment", "inviter_id": "987654321098765432",
                   "uses": 8, "max_uses": 10},
}


def sample_row(event_type: str) -> dict:
    """Fixed sample identity; never represents a live member or moderator."""
    if event_type not in EVENT_STYLE:
        raise ValueError("Unsupported member event")
    return {
        "event_type": event_type, "user_id": "123456789012345678",
        "display_name": "Sample member", "username": "sample_member",
        "occurred_at": datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc),
        "joined_at": datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        "account_created_at": datetime(2020, 3, 15, 9, 30, tzinfo=timezone.utc),
        "member_count": 1284, "roles": ["Member", "CWL player"],
        "moderator_id": "987654321098765432", "reason": "Example reason",
        "avatar": None, "avatar_type": None,
        "details": SAMPLE_DETAILS.get(event_type),
    }
