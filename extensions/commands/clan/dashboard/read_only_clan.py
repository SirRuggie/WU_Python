"""Read-only compatibility for old clan administration controls."""
import re
from urllib.parse import quote

from .permissions import require_dashboard_role

ROLE_ID = 993015846442127420
BASE = "https://dash.warriorsunited.cc/clans"
FIELDS = (
    ("name", "Name"), ("type", "Clan type"), ("th_requirements", "Minimum Town Hall"),
    ("leader_id", "Leader"), ("leader_role_id", "Leader role"), ("role_id", "Clan role"),
    ("chat_channel_id", "Chat channel"), ("announcement_id", "Announcement channel"),
    ("rules_channel_id", "Rules channel"), ("leadership_channel_id", "Leadership channel"),
    ("thread_id", "Clan thread"), ("logo", "Logo"), ("banner", "Banner"),
    ("profile", "Profile"), ("emoji", "Emoji"),
)


def safe_text(value):
    # No mentions, markdown links or formatting from stored external text.
    text = str(value or "Not set").replace("@", "@\u200b")
    return re.sub(r"([\\\x60*_~|<>\[\]])", r"\\\1", text)[:80]


async def show_clan(ctx, mongo, action_id=""):
    """Never mutate storage or call Clash/Discord transport beyond the response."""
    if not await require_dashboard_role(ctx, ROLE_ID, "Clan Management"):
        return
    match = re.search(r"#[A-Za-z0-9]{3,15}(?=$|[^A-Za-z0-9])", str(action_id))
    tag = match.group(0).upper() if match else None
    row = await mongo.clans.find_one({"tag": tag}) if tag else None
    link = BASE + "/" + quote(tag, safe="") if tag else BASE
    lines = ["Clan editing has moved to the dashboard."]
    if row:
        lines.append("Current settings:")
        lines.extend(f"{label}: {safe_text(row.get(field))}" for field, label in FIELDS)
    elif tag:
        lines.append("This clan is no longer in the family directory.")
    lines.append(f"Edit this on the dashboard › <{link}>")
    lines.append("Restore removed clans: Dashboard → Family clans → History")
    await ctx.respond("\n".join(lines), ephemeral=True, user_mentions=False,
                      role_mentions=False, mentions_everyone=False)
