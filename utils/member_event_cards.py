"""Pure Discord card payloads shared by gateway delivery and dashboard previews."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from utils import dashboard_urls
from utils.member_events import GUILD_ID, HISTORY_TYPES, safe_text

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
    "unban": ("🔓", "Member unbanned", "was unbanned", 0x4CAF82),
    "role_create": ("🏷️", "Role created", "created", 0x2BA66A),
    "role_update": ("🏷️", "Role updated", "updated", 0x6B7FD7),
    "role_delete": ("🏷️", "Role deleted", "deleted", 0xD34A4A),
    "roles_added": ("➕", "Roles added", "had roles added", 0x2BA66A),
    "roles_removed": ("➖", "Roles removed", "had roles removed", 0xD34A4A),
    "message_delete": ("🗑️", "Message deleted", "had a message deleted", 0xD34A4A),
    "message_edit": ("📝", "Message edited", "edited a message", 0x6B7FD7),
    "message_bulk_delete": ("🧹", "Messages bulk deleted", "bulk deleted", 0xA8384B),
    "channel_create": ("#️⃣", "Channel created", "created", 0x2BA66A),
    "channel_update": ("#️⃣", "Channel updated", "updated", 0x6B7FD7),
    "channel_delete": ("#️⃣", "Channel deleted", "deleted", 0xD34A4A),
    "channel_permissions": ("🔐", "Permissions changed", "changed", 0xD8B13A),
    "thread_delete": ("🧵", "Thread deleted", "deleted", 0xD34A4A),
    "thread_lock": ("🔒", "Thread locked", "locked", 0xE69935),
    "server_update": ("⚙️", "Server updated", "updated", 0x6B7FD7),
    "emoji": ("😀", "Emoji changed", "changed", 0x8A8F98),
    "sticker": ("🖼️", "Sticker changed", "changed", 0x8A8F98),
    "app": ("🧩", "App changed", "changed", 0x4C9BE8),
    "webhook": ("🪝", "Webhook changed", "changed", 0x8A8F98),
    "automod": ("🛡️", "AutoMod rule changed", "changed", 0xE69935),
}
# Kinds about a guild object (role, channel, ...) rather than a member.
OBJECT_NOUNS = {
    "role_create": "Role", "role_update": "Role", "role_delete": "Role",
    "channel_create": "Channel", "channel_update": "Channel", "channel_delete": "Channel",
    "channel_permissions": "Channel", "thread_delete": "Thread", "thread_lock": "Thread",
    "server_update": "Server", "emoji": "Emoji", "sticker": "Sticker", "app": "App",
    "webhook": "Webhook", "automod": "AutoMod rule",
}
OBJECT_KINDS = tuple(OBJECT_NOUNS)
# Kinds whose subject can be shown as a live mention (it resolves in Discord).
MENTIONS = {"role_update": "@&", "channel_create": "#", "channel_update": "#",
            "channel_permissions": "#", "thread_lock": "#"}
OPAQUE_FIELDS = ("permissions", "allow", "deny", "permission_overwrites")
EXTRA_KINDS = ("timeout_add", "timeout_remove", "member_update", "link",
               "invite_create", "invite_delete", "invite_use", "unban", "roles_added",
               "roles_removed", "message_delete", "message_edit", "message_bulk_delete",
               *OBJECT_KINDS)
USER_KINDS = ("timeout_add", "timeout_remove", "member_update", "link", "invite_use", "unban",
              "roles_added", "roles_removed", "message_delete", "message_edit")
HISTORY_BUTTON_KINDS = HISTORY_TYPES
TRANSCRIPT_NAME = "message-transcript.txt"
FIELD_LABELS = {"nickname": "Nickname", "username": "Username", "global_name": "Display name",
                "avatar": "Avatar", "guild_avatar": "Server avatar", "discriminator": "Discriminator"}
DEFAULT_AVATAR = "https://cdn.discordapp.com/embed/avatars/0.png"
CDN_PREFIX = "https://cdn.discordapp.com/"
# List caps; the rest is summarized as "+N more".
MAX_ROLES = MAX_CHANGES = MAX_URLS = MAX_ATTACHMENTS = 10
MAX_PERMISSION_CHANGES = 15
# Discord limits, with margin: V2 text is capped at 4,000 in total.
V2_TEXT_LIMIT = 3800
EMBED_DESCRIPTION_LIMIT = 4000
EMBED_FIELD_LIMIT = 1000
EMBED_TOTAL_LIMIT = 5800
RECOVERED_LINE = "Recovered after restart"


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
    return ", ".join(names[:MAX_ROLES]) + (f" +{len(names) - MAX_ROLES} more" if len(names) > MAX_ROLES else "")


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


def _named(value: object, limit: int = 120) -> str:
    text = safe_text(value, limit)
    return text if text.replace("\u200d", "").strip() else ""


def _ordinal(number: int) -> str:
    suffix = "th" if 10 <= number % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(number % 10, "th")
    return f"{number}{suffix}"


def _account_age(row: dict) -> str | None:
    created, now = _moment(row.get("account_created_at")), _moment(row.get("occurred_at"))
    if not created or not now:
        return None
    age = _since(created, now)
    days = (now.replace(tzinfo=now.tzinfo or timezone.utc)
            - created.replace(tzinfo=created.tzinfo or timezone.utc)).days
    return f"{age} · New account" if days < 7 else age


def _cut(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    end = max(limit - 1, 0)
    if text[end:end + 1] == "\u200b" and text[end - 1:end] == "@":
        end -= 1  # Keep "@" and its zero-width space together.
    cut = text[:end]
    if (len(cut) - len(cut.rstrip("\\"))) % 2:
        cut = cut[:-1]  # Never end on half an escape.
    return cut + "…"


FIT_FLOOR = 40  # A line is cut to this many characters before anything is dropped.
_MORE_LINE = re.compile(r"\+(\d+) more")


def _hide(lines: list[str], dropped: int) -> None:
    """Fold ``dropped`` removed items into the one "+N more" line before the footer."""
    for index in range(3, len(lines) - 1):
        match = _MORE_LINE.fullmatch(lines[index])
        if match:
            lines[index] = f"+{int(match.group(1)) + dropped} more"
            return
    lines.insert(len(lines) - 1, f"+{dropped} more")


def _fit(lines: list[str], budget: int, joiner: int = 0) -> list[str]:
    """Shorten the longest field lines, then drop trailing fields, until the total fits.

    Name, title, main line and footer stay; every dropped field is counted in "+N more".
    """
    lines = list(lines)
    size = lambda: sum(map(len, lines)) + joiner * (len(lines) - 1)
    while size() > budget:
        excess = size() - budget
        middle = [i for i in range(1, len(lines) - 1) if len(lines[i]) > FIT_FLOOR]
        if middle:
            index = max(middle, key=lambda i: len(lines[i]))
            lines[index] = _cut(lines[index], max(len(lines[index]) - excess, FIT_FLOOR))
            continue
        fields = [i for i in range(3, len(lines) - 1) if not _MORE_LINE.fullmatch(lines[i])]
        if fields:
            del lines[fields[-1]]
            _hide(lines, 1)
            continue
        longest = [i for i in range(len(lines)) if len(lines[i]) > FIT_FLOOR // 2]
        if not longest:
            return lines
        index = max(longest, key=lambda i: len(lines[i]))
        lines[index] = _cut(lines[index], max(len(lines[index]) - excess, FIT_FLOOR // 2))
    return lines


def _guard_embed(embed: dict) -> dict:
    """Forum starter embed within Discord's description, field and total limits."""
    embed["description"] = _cut(embed.get("description", ""), EMBED_DESCRIPTION_LIMIT)
    for field in embed.get("fields", ()):
        field["value"] = _cut(field["value"], EMBED_FIELD_LIMIT)
    other = sum(len(field.get("name", "")) + len(field["value"]) for field in embed.get("fields", ()))
    embed["description"] = _cut(embed["description"], EMBED_TOTAL_LIMIT - other)
    return embed


def _more(total: int, shown: int) -> list[str]:
    return [f"+{total - shown} more"] if total > shown else []


def _change_lines(details: dict, limit: int = MAX_CHANGES) -> list[str]:
    lines = []
    changes = details.get("changes") or []
    for change in changes[:limit]:
        if not isinstance(change, dict) or not change.get("field"):
            continue
        field = str(change["field"])
        label = safe_text(field.replace("_", " ").capitalize(), 40)
        if field in OPAQUE_FIELDS or (change.get("before") is None and change.get("after") is None):
            lines.append(f"**{label}**\nChanged")
        else:
            before = _inert(change.get("before"), 100) or "None"
            after = _inert(change.get("after"), 100) or "None"
            lines.append(f"**{label}**\n{before} → {after}")
    return lines + _more(len(changes), limit)


def _attachment_line(details: dict) -> str | None:
    raw = details.get("attachments") or []
    items = [item for item in raw[:MAX_ATTACHMENTS] if isinstance(item, dict)]
    names = [f"{safe_text(item.get('name'), 80) or 'File'} ({safe_text(item.get('type'), 40) or 'unknown'})"
             for item in items]
    return "**Attachments**\n" + "\n".join(names + _more(len(raw), MAX_ATTACHMENTS)) if names else None


def transcript_file(row: dict) -> tuple[str, bytes, str] | None:
    """The bulk-delete transcript as an upload (name, bytes, content type)."""
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    text = details.get("transcript")
    if row.get("event_type") != "message_bulk_delete" or not isinstance(text, str) or not text:
        return None
    return TRANSCRIPT_NAME, text.encode("utf-8"), "text/plain; charset=utf-8"


def _extra_content(row: dict, test_staff_id: object = None) -> tuple[list[str], str | None]:
    kind = row["event_type"]
    icon, title, action, _ = EVENT_STYLE[kind]
    details = row.get("details") if isinstance(row.get("details"), dict) else {}
    uid = _snowflake(row.get("user_id")) if kind in USER_KINDS else None
    if kind in USER_KINDS and uid is None:
        raise ValueError("A trusted member ID is required for a profile card")
    name = _named(row.get("display_name")) or (
        "Unknown member" if uid else OBJECT_NOUNS.get(kind)
        or ("Channel" if kind == "message_bulk_delete" else "Unknown invite"))
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
        changes = details.get("changes") or []
        for change in changes[:MAX_CHANGES]:
            label = FIELD_LABELS.get(change.get("field"))
            if not label:
                continue
            if change.get("field") in ("avatar", "guild_avatar"):
                fields.append(f"**{label}**\nChanged")
            else:
                before = _named(change.get("before"), 100) or "None"
                after = _named(change.get("after"), 100) or "None"
                fields.append(f"**{label}**\n{before} → {after}")
        fields += _more(len(changes), MAX_CHANGES)
        actor = _snowflake(details.get("actor_id"))
        if actor:
            fields.append(f"**Changed by**\n<@{actor}>")
    elif kind == "link":
        channel = _snowflake(details.get("channel_id"))
        if channel:
            main += f" in <#{channel}>"
        fields.append(f"**Message**\n{_inert(details.get('content'), 500) or 'No text'}")
        raw_urls = details.get("urls") or []
        urls = [str(url).replace("`", "")[:200] for url in raw_urls[:MAX_URLS]]
        if urls:
            fields.append("**Links**\n" + "\n".join(
                [f"`{url}`" for url in urls] + _more(len(raw_urls), MAX_URLS)))
    elif kind == "unban":
        main += by
        fields = [reason]
    elif kind in ("roles_added", "roles_removed"):
        main += f" by <@{moderator}>" if moderator else ""
        raw_roles = details.get("roles") or []
        names = [name for name in (safe_text(item, 60) for item in raw_roles[:MAX_ROLES]) if name]
        fields.append("**Roles**\n" + (", ".join(names) or "Unavailable")
                      + "".join(f" {line}" for line in _more(len(raw_roles), MAX_ROLES)))
    elif kind in ("message_delete", "message_edit"):
        channel = _snowflake(details.get("channel_id"))
        main += f" in <#{channel}>" if channel else ""
        if kind == "message_delete":
            main += f" by <@{moderator}>" if moderator else ""
            fields.append(f"**Message**\n{_inert(details.get('content'), 500) or 'No text'}")
        else:
            fields.append(f"**Before**\n{_inert(details.get('before'), 500) or 'No text'}")
            fields.append(f"**After**\n{_inert(details.get('after'), 500) or 'No text'}")
        attachments = _attachment_line(details)
        if attachments:
            fields.append(attachments)
    elif kind == "message_bulk_delete":
        channel = _snowflake(details.get("channel_id"))
        count = details.get("count")
        main = f"{count:,} messages were deleted" if isinstance(count, int) and count >= 0 else "Messages were deleted"
        main += f" in <#{channel}>" if channel else ""
        main += f" by <@{moderator}>" if moderator else ""
        if transcript_file(row):
            fields.append("**Transcript**\nAttached")
    elif kind in OBJECT_KINDS:
        target = _snowflake(details.get("target_id"))
        prefix = MENTIONS.get(kind)
        ref = f"<{prefix}{target}>" if prefix and target else f"**{name}**"
        verb = safe_text(details.get("action"), 20) or action
        main = f"{OBJECT_NOUNS[kind]} {ref} was {verb}" + (f" by <@{moderator}>" if moderator else "")
        fields = _change_lines(details, MAX_PERMISSION_CHANGES if kind == "channel_permissions" else MAX_CHANGES)
        subject = _snowflake(details.get("subject_id"))
        if subject and details.get("subject_type") in ("role", "member"):
            fields.append(f"**Applies to**\n<{'@&' if details['subject_type'] == 'role' else '@'}{subject}>")
        elif details.get("subject_name"):
            fields.append(f"**Applies to**\n{safe_text(details['subject_name'], 80)}")
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
    lines, uid = _body(row, test_staff_id)
    details = row.get("details")
    if isinstance(details, dict) and details.get("recovered"):
        lines.insert(-1, RECOVERED_LINE)  # Before the footer.
    return lines, uid


def _body(row: dict, test_staff_id: object = None) -> tuple[list[str], str | None]:
    kind = row["event_type"]
    if kind in EXTRA_KINDS:
        return _extra_content(row, test_staff_id)
    icon, title, action, _ = EVENT_STYLE[kind]
    uid = _snowflake(row.get("user_id"))
    if uid is None:
        raise ValueError("A trusted member ID is required for a profile card")
    name = _named(row.get("display_name")) or "Unknown member"
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
        details = row.get("details") if isinstance(row.get("details"), dict) else {}
        age = _account_age(row)
        if age:
            fields.append(f"**Account age**\n{age}")
        joins = details.get("join_count")
        if isinstance(joins, int) and joins >= 2:
            fields.append(f"**Join**\n{_ordinal(joins)} join")
        via = _named(details.get("invite"), 60)
        if via:
            fields.append(f"**Invite**\nvia {via}")
    else:
        fields.append(f"**Joined**\n{_date(row.get('joined_at'))}")
        if kind == "leave":
            if isinstance(row.get("joined_at"), datetime):
                fields.append(f"**Time in server**\n{_since(row.get('joined_at'), row.get('occurred_at'))}")
            if row.get("roles") is not None:
                fields.append(f"**Roles**\n{_roles(row)}")
        else:
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
    history = dashboard_urls.member_history_url(uid) if uid and row["event_type"] in HISTORY_BUTTON_KINDS else None
    if history:
        buttons.append({"type": 2, "style": 5, "label": "Member history ↗", "url": history})
    if row["event_type"] in ("link", "message_edit") and channel and message:
        buttons.append({"type": 2, "style": 5, "label": "Jump to message ↗",
                        "url": f"https://discord.com/channels/{GUILD_ID}/{channel}/{message}"})
    return buttons


def _profile_button(uid: str) -> dict:
    return {"type": 2, "style": 5, "label": "View profile ↗",
            "url": f"https://discord.com/users/{uid}"}


def build_card(row: dict, test_staff_id: object = None) -> dict:
    """Components V2 message for text channels and existing forum-post replies."""
    lines, uid = _content(row, test_staff_id)
    name, title, main, *rest = _fit([f"**{lines[0]}**", *lines[1:]], V2_TEXT_LIMIT)
    footer = rest.pop()
    avatar = _avatar_url(row)
    header = ({"type": 9, "components": [{"type": 10, "content": name}],
               "accessory": {"type": 11, "media": {"url": avatar},
                             "description": "Member avatar"}} if avatar
              else {"type": 10, "content": name})
    buttons = _buttons(row, uid)
    children = [
        header,
        {"type": 10, "content": title},
        {"type": 10, "content": main},
        *({"type": 10, "content": field} for field in rest),
        *([{"type": 13, "file": {"url": f"attachment://{TRANSCRIPT_NAME}"}}] if transcript_file(row) else []),
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
    fitted = _fit([f"**{lines[0]}**", *lines[1:]], EMBED_DESCRIPTION_LIMIT, joiner=2)
    description = "\n\n".join(fitted)
    avatar = _avatar_url(row)
    buttons = _buttons(row, uid)
    return {
        "embeds": [_guard_embed({"description": description, "color": accent(row["event_type"]),
                                 **({"thumbnail": {"url": avatar}} if avatar else {})})],
        **({"components": [{"type": 1, "components": buttons}]} if buttons else {}),
        "allowed_mentions": {"parse": []},
    }


SAMPLE_DETAILS = {
    "join": {"join_count": 3, "invite": "Spring recruitment"},
    "role_create": {"action": "created", "target_id": "423456789012345678"},
    "role_update": {"action": "updated", "target_id": "423456789012345678",
                    "changes": [{"field": "name", "before": "Recruit", "after": "Member"},
                                {"field": "permissions", "before": None, "after": None}]},
    "role_delete": {"action": "deleted", "target_id": "423456789012345678"},
    "roles_added": {"roles": ["CWL player", "Member"]},
    "roles_removed": {"roles": ["Recruit"]},
    "message_delete": {"channel_id": "223456789012345678", "message_id": "323456789012345678",
                       "content": "Sample message that was deleted.",
                       "attachments": [{"name": "screenshot.png", "type": "image/png"}]},
    "message_edit": {"channel_id": "223456789012345678", "message_id": "323456789012345678",
                     "before": "Sample message before the edit.", "after": "Sample message after the edit."},
    "message_bulk_delete": {"channel_id": "223456789012345678", "count": 12},
    "channel_create": {"action": "created", "target_id": "223456789012345678", "type": "text"},
    "channel_update": {"action": "updated", "target_id": "223456789012345678",
                       "changes": [{"field": "topic", "before": "Old topic", "after": "New topic"}]},
    "channel_delete": {"action": "deleted", "target_id": "223456789012345678"},
    "channel_permissions": {"action": "changed", "target_id": "223456789012345678",
                            "subject_type": "role", "subject_id": "423456789012345678",
                            "changes": [{"field": "allow", "before": None, "after": None}]},
    "thread_delete": {"action": "deleted", "target_id": "523456789012345678"},
    "thread_lock": {"action": "locked", "target_id": "523456789012345678"},
    "server_update": {"action": "updated", "changes": [
        {"field": "name", "before": "Old server", "after": "Warriors United"}]},
    "emoji": {"action": "added", "target_id": "623456789012345678"},
    "sticker": {"action": "changed", "target_id": "623456789012345678",
                "changes": [{"field": "name", "before": "Old", "after": "New"}]},
    "app": {"action": "added", "target_id": "723456789012345678"},
    "webhook": {"action": "removed", "target_id": "823456789012345678"},
    "automod": {"action": "added", "target_id": "923456789012345678"},
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
    about_member = event_type not in OBJECT_KINDS and event_type != "message_bulk_delete"
    return {
        "event_type": event_type, "user_id": "123456789012345678" if about_member else "0",
        "display_name": "Sample member" if about_member else (
            f"Sample {OBJECT_NOUNS.get(event_type, 'channel').lower()}"),
        "username": "sample_member",
        "occurred_at": datetime(2026, 10, 29, 18, 0, tzinfo=timezone.utc),
        "joined_at": datetime(2024, 6, 1, 12, 0, tzinfo=timezone.utc),
        "account_created_at": datetime(2020, 3, 15, 9, 30, tzinfo=timezone.utc),
        "member_count": 1284, "roles": ["Member", "CWL player"],
        "moderator_id": "987654321098765432", "reason": "Example reason",
        "avatar": None, "avatar_type": None,
        "details": SAMPLE_DETAILS.get(event_type),
    }
