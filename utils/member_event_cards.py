"""Pure Discord card payloads shared by gateway delivery and dashboard previews."""
from __future__ import annotations

from datetime import datetime, timezone

from utils.member_events import safe_text

EVENT_STYLE = {
    "join": ("👋", "Member joined", "joined", 0x2BA66A),
    "leave": ("🚪", "Member left", "left", 0xD34A4A),
    "kick": ("👢", "Member kicked", "was kicked", 0xE69935),
    "ban": ("🔨", "Member banned", "was banned", 0xA8384B),
}
DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"


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


def _content(row: dict, test_staff_id: object = None) -> tuple[list[str], str]:
    kind = row["event_type"]
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


def _avatar_url(row: dict) -> str:
    filename = avatar_filename(row)
    return f"attachment://{filename}" if filename else DEFAULT_AVATAR


def _profile_button(uid: str) -> dict:
    return {"type": 2, "style": 5, "label": "View profile ↗",
            "url": f"https://discord.com/users/{uid}"}


def build_card(row: dict, test_staff_id: object = None) -> dict:
    """Components V2 message for text channels and existing forum-post replies."""
    lines, uid = _content(row, test_staff_id)
    name, title, main, *rest = lines
    footer = rest.pop()
    children = [
        {"type": 9, "components": [{"type": 10, "content": f"**{name}**"}],
         "accessory": {"type": 11, "media": {"url": _avatar_url(row)},
                       "description": "Member avatar"}},
        {"type": 10, "content": title},
        {"type": 10, "content": main},
        *({"type": 10, "content": field} for field in rest),
        {"type": 14, "divider": True, "spacing": 1},
        {"type": 10, "content": footer},
        {"type": 1, "components": [_profile_button(uid)]},
    ]
    return {"flags": 1 << 15, "components": [
        {"type": 17, "accent_color": accent(row["event_type"]), "components": children}
    ], "allowed_mentions": {"parse": []}}


def build_forum_message(row: dict, test_staff_id: object = None) -> dict:
    """Forum starters cannot set the V2 flag; retain one embed-based starter."""
    lines, uid = _content(row, test_staff_id)
    name, title, main, *rest = lines
    description = "\n\n".join([f"**{name}**", title, main, *rest])
    return {
        "embeds": [{"description": description, "color": accent(row["event_type"]),
                    "thumbnail": {"url": _avatar_url(row)}}],
        "components": [{"type": 1, "components": [_profile_button(uid)]}],
        "allowed_mentions": {"parse": []},
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
    }
