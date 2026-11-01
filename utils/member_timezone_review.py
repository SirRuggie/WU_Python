"""Pure nickname review classification; no Discord transport or storage."""

from utils.member_timezone_import import nickname_name
from utils.member_timezones import nickname


def preview_rows(members):
    rows = []
    for member in members:
        if member.get("bot"):
            continue
        profile = member.get("profile")
        item = dict(
            discord_id=member["discord_id"],
            name=member["name"],
            old_nickname=member["nickname"],
            new_nickname=None,
            revision=(profile or {}).get("revision", 0),
            skip_reason=member.get("skip_reason"),
            needs_review=False,
        )
        if item["skip_reason"]:
            category = "cant_rename"
        elif not profile:
            category = "no_time_zone"
            item["skip_reason"] = "No time zone recognized"
        elif not profile.get("country"):
            category = "needs_flag"
            item["skip_reason"] = "Choose a country flag"
        else:
            parsed = nickname_name(member["nickname"], member["name"])
            item["needs_review"] = parsed["needs_review"]
            try:
                item["new_nickname"] = nickname(
                    parsed["name"], profile["zone_id"], profile["country"]
                )
                if item["new_nickname"] == item["old_nickname"]:
                    category = "already_done"
                    item["skip_reason"] = "Already standardized"
                else:
                    category = "check_name" if item["needs_review"] else "will_change"
            except ValueError as error:
                category = "cant_rename"
                item["skip_reason"] = str(error)
        rows.append(dict(item, category=category))
    return rows
