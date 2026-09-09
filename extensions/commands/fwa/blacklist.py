# extensions/commands/fwa/blacklist.py
"""
/fwa blacklist - manage the ongoing list of clans blacklisted from FWA wars.

Entries are added automatically when staff pick "Blacklisted" in
/fwa war-plans (see war_plans.py), or by hand with `/fwa blacklist add`.
See docs/fwa-blacklist.md for what is stored and why this list has to be
staff-maintained (ChocolateClash association is not readable).
"""

import lightbulb
import coc

from datetime import datetime

from extensions.commands.fwa import loader, fwa
from extensions.commands.fwa.war_plans import FWA_WAR_PLANS_CONFIG
from utils.mongo import MongoClient
from utils.fwa_blacklist import add_blacklisted, remove_blacklisted, list_blacklisted
from utils.fwa_points_parser import sanitize_tag
from utils.constants import GOLD_ACCENT

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
)

# Same FWA Clan Rep role gate as /fwa war-plans - pulled from the same config
# dict so the two commands cannot drift apart.
FWA_CLAN_REP_ROLE_ID = FWA_WAR_PLANS_CONFIG["fwa_clan_rep_role_id"]

blacklist = fwa.subgroup("blacklist", "Manage the FWA opponent blacklist")

# One Text component per entry is unbounded and will cross Discord's 1-4000
# char Text-display cap (and the component-count cap) as the list grows - see
# extensions/commands/tickets/manage.py:32-39 for the same bound hit by ticket
# lists. Here the fix is pagination: a fixed page size plus a defensive
# character clamp for the rare page with unusually long names.
BLACKLIST_PAGE_SIZE = 25
MAX_LIST_CONTENT = 3500


def _format_added_date(added_at) -> str:
    if not added_at:
        return "unknown"
    try:
        return datetime.fromisoformat(added_at).date().isoformat()
    except ValueError:
        return added_at[:10] if len(added_at) >= 10 else added_at


def _format_entry_line(doc: dict) -> str:
    tag = doc.get("_id", "")
    name = doc.get("name") or tag
    classification = doc.get("classification")
    source = doc.get("source") or "unknown"
    added_date = _format_added_date(doc.get("added_at"))
    parts = [name, f"#{tag}"]
    if classification:
        parts.append(classification)
    parts.append(source)
    parts.append(f"added {added_date}")
    return " — ".join(parts)


@blacklist.register()
class BlacklistList(
    lightbulb.SlashCommand,
    name="list",
    description="Show every clan on the FWA blacklist",
):
    page = lightbulb.integer(
        "page",
        "Page number (25 entries per page)",
        default=1,
        min_value=1,
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)

        entries = await list_blacklisted(mongo)  # already sorted by name
        if not entries:
            await ctx.respond("The FWA blacklist is empty.", ephemeral=True)
            return

        total = len(entries)
        total_pages = max(1, -(-total // BLACKLIST_PAGE_SIZE))  # ceil division
        page_number = min(self.page, total_pages)

        start = (page_number - 1) * BLACKLIST_PAGE_SIZE
        page_entries = entries[start:start + BLACKLIST_PAGE_SIZE]
        lines = [_format_entry_line(doc) for doc in page_entries]

        body_text = "\n".join(lines)
        if len(body_text) > MAX_LIST_CONTENT:
            kept, used = [], 0
            for line in lines:
                if used + len(line) + 1 > MAX_LIST_CONTENT:
                    break
                kept.append(line)
                used += len(line) + 1
            hidden = len(lines) - len(kept)
            body_text = "\n".join(kept) + f"\n-# …{hidden} more not shown on this page."

        header = f"## 🚫 FWA Blacklist — page {page_number} of {total_pages}, {total} total"
        body = [Text(content=header), Separator(divider=True), Text(content=body_text)]
        await ctx.respond(
            components=[Container(accent_color=GOLD_ACCENT, components=body)],
            ephemeral=True,
        )


@blacklist.register()
class BlacklistAdd(
    lightbulb.SlashCommand,
    name="add",
    description="Add a clan to the FWA blacklist",
):
    tag = lightbulb.string("tag", "Clan tag (with or without #)")
    name = lightbulb.string(
        "name",
        "Clan name (looked up from the CoC API if left blank)",
        default="",
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
        coc_client: coc.Client = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        if not ctx.member or FWA_CLAN_REP_ROLE_ID not in ctx.member.role_ids:
            await ctx.respond("❌ You must have the FWA Clan Rep role to use this command.", ephemeral=True)
            return

        t = sanitize_tag(self.tag)
        if not t:
            await ctx.respond("❌ Invalid tag.", ephemeral=True)
            return

        name = self.name.strip()
        if not name:
            try:
                clan = await coc_client.get_clan(f"#{t}")
                name = clan.name
            except Exception as e:
                await ctx.respond(
                    f"❌ Could not look up the clan name from the API ({type(e).__name__}). "
                    f"Provide `name` explicitly.",
                    ephemeral=True,
                )
                return

        author_name = ctx.member.display_name if ctx.member else ctx.user.username
        added_tag = await add_blacklisted(mongo, t, name, ctx.user.id, author_name, "manual")
        await ctx.respond(f"✅ Added **{name}** (`#{added_tag}`) to the FWA blacklist.", ephemeral=True)


@blacklist.register()
class BlacklistRemove(
    lightbulb.SlashCommand,
    name="remove",
    description="Remove a clan from the FWA blacklist",
):
    tag = lightbulb.string("tag", "Clan tag to remove")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: lightbulb.Context, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)

        if not ctx.member or FWA_CLAN_REP_ROLE_ID not in ctx.member.role_ids:
            await ctx.respond("❌ You must have the FWA Clan Rep role to use this command.", ephemeral=True)
            return

        t = sanitize_tag(self.tag)
        if not t:
            await ctx.respond("❌ Invalid tag.", ephemeral=True)
            return

        removed = await remove_blacklisted(mongo, t)
        if removed:
            await ctx.respond(f"✅ Removed `#{t}` from the FWA blacklist.", ephemeral=True)
        else:
            await ctx.respond(f"❌ `#{t}` was not on the FWA blacklist.", ephemeral=True)


loader.command(fwa)
