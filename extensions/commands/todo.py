"""/todo - what each of your linked Clash accounts still owes.

DM-first. Three views (war hits, CWL hits, raids) switched by buttons; only
ACTIONABLE accounts appear. See docs/todo-dashboard-proposal.md.

Design rules enforced here, each of which cost real investigation to establish:

  ONE COLON in every custom_id. The dispatcher splits at the FIRST colon and
  everything after it is the state key, so `action:{id}:{page}` makes the state
  key a composite that misses the lookup. manage_roles.py:366 does exactly that
  and its pagination has never worked. View lives in the action name, page in
  the action_id, and nothing else.

  STATELESS. Nothing is written to Mongo. Page comes from the custom_id, user
  identity from ctx.user.id on the interaction. So the dispatcher's state
  lookup always misses, which is fine and intended: every handler defaults all
  its parameters and reads only action_id. A missing state document cannot
  break a panel that never had one, and a /todo panel sitting in DM history for
  a year keeps working.

  NO ctx.guild_id. It is None in a DM, and the house header pattern
  (clan/dashboard/dashboard.py:44 -> bot.cache.get_guild(ctx.guild_id)
  .make_icon_url()) raises AttributeError there. ctx.member is None too, so no
  role checks anywhere in this file.

  UNICODE EMOJI ONLY, deliberately. utils.emoji is the house style, but an
  attribute typo there is an AttributeError inside a render path, and nothing
  in this file has ever been executed. Swap to emojis.* once it has run.
"""

import coc
import lightbulb
import hikari

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)

from extensions.components import register_action
from utils import todo_data
from utils.clash_links import resolve_tags
from utils.constants import RED_ACCENT
from utils.mongo import MongoClient

loader = lightbulb.Loader()

PAGE_SIZE = 20
VIEW_WAR = "war"
VIEW_CWL = "cwl"
VIEW_RAID = "raid"

# ClashKing asks for exactly one thing in return for a free, unauthenticated
# API: credit. Their terms read "Please credit if using these stats in your
# project, Creator Code: ClashKing". This line is that credit.
ATTRIBUTION = "-# Data via ClashKing · Creator Code: ClashKing"


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _panel(body_components: list) -> list:
    return [Container(accent_color=RED_ACCENT, components=body_components)]


def _notice(title: str, body: str) -> list:
    """A single-message panel. Used for every state that is not a dashboard."""
    return _panel([
        Text(content=f"## {title}"),
        Separator(divider=True),
        Text(content=body),
        Media(items=[MediaItem(media="assets/Red_Footer.png")]),
    ])


def _nav_row(view: str, page: int, counts: dict) -> ActionRow:
    """Four buttons in one ActionRow.

    Deliberately NOT four Sections with button accessories. A Section holds
    exactly one accessory plus a mandatory Text Display, so four nav buttons as
    Sections cost 12 components against 5 for a row - and that 7-component
    difference is the entire row budget.

    Badge counts live in the labels. `None` means the section could not be read
    and renders as `?`, never as `0` - an unreadable section must never look
    like an empty one.
    """
    def label(stem: str, key: str) -> str:
        value = counts.get(key)
        if value is None:
            return f"{stem} (?)"
        if value == 0:
            return f"{stem} ✅"
        return f"{stem} ({value})"

    return ActionRow(components=[
        Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"todo_war:{page if view == VIEW_WAR else 0}",
            label=label("War", VIEW_WAR),
            is_disabled=view == VIEW_WAR,
        ),
        Button(
            style=hikari.ButtonStyle.PRIMARY,
            custom_id=f"todo_cwl:{page if view == VIEW_CWL else 0}",
            label=label("CWL", VIEW_CWL),
            is_disabled=view == VIEW_CWL,
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id="todo_raid:0",
            label="Raids (soon)",
            is_disabled=True,
        ),
        Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"todo_refresh:{view}|{page}",
            label="Refresh",
        ),
    ])


def _row_line(row) -> str:
    return f"▸ {row.account} `{row.used}/{row.limit}`"


def _render_rows(rows: list) -> list:
    """Rows grouped by clan, one Text Display per clan.

    Grouping states each war deadline once instead of repeating it on every
    row, which is what the component budget freed up by the ActionRow nav buys.
    """
    if not rows:
        return []

    order: list[str] = []
    grouped: dict[str, list] = {}
    for row in rows:
        if row.clan_tag not in grouped:
            grouped[row.clan_tag] = []
            order.append(row.clan_tag)
        grouped[row.clan_tag].append(row)

    out: list = []
    for index, clan_tag in enumerate(order):
        members = grouped[clan_tag]
        head = f"### ⚔️ {members[0].clan_name}"
        ends = members[0].ends_at
        if ends:
            head += f" · ends <t:{ends}:R>"
        lines = "\n".join(_row_line(r) for r in members)
        out.append(Text(content=f"{head}\n{lines}"))
        if index != len(order) - 1:
            out.append(Separator(divider=False, spacing=hikari.SpacingType.SMALL))
    return out


def render_dashboard(view: str, page: int, data: dict) -> list:
    """The dashboard itself.

    `data` maps view name -> ViewData. A view whose ViewData is None could not
    be computed at all.
    """
    counts = {k: (v.count if v is not None and v.ok else None) for k, v in data.items()}
    current = data.get(view)

    body: list = [Text(content="## 📋 Your To-Do")]

    if current is None or not current.ok:
        # RULE: could-not-read must never render as all-caught-up.
        body.append(Separator(divider=True))
        body.append(Text(content=(
            "⚠️ **Couldn't read this section.**\n"
            "The Clash API or the proxy didn't answer. This is not the same as "
            "having nothing to do — press Refresh in a minute."
        )))
        pages = 1
        page = 0
    else:
        rows = current.rows
        pages = max(1, (len(rows) + PAGE_SIZE - 1) // PAGE_SIZE)
        page = max(0, min(page, pages - 1))
        window = rows[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

        body.append(Separator(divider=True))
        if not rows:
            body.append(Text(content="**All caught up.**"))
        else:
            body.extend(_render_rows(window))

        if current.notes:
            body.append(Separator(divider=True))
            body.append(Text(content="\n".join(f"-# {n}" for n in current.notes)))

    body.append(Separator(divider=True))
    body.append(_nav_row(view, page, counts))

    if pages > 1:
        body.append(ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"todo_{view}:{max(0, page - 1)}",
                label="◀",
                is_disabled=page == 0,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"todo_{view}:{page}",
                label=f"Page {page + 1}/{pages}",
                is_disabled=True,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"todo_{view}:{min(pages - 1, page + 1)}",
                label="▶",
                is_disabled=page >= pages - 1,
            ),
        ]))

    body.append(Text(content=ATTRIBUTION))
    body.append(Media(items=[MediaItem(media="assets/Red_Footer.png")]))
    return _panel(body)


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

async def _load(bot, coc_client, discord_id: int, force: bool = False):
    """Resolve tags and compute every section.

    Returns (data, problem). `problem` is a ready-to-render component list when
    the dashboard cannot be shown at all; otherwise None.

    All sections compute together because the nav badges show every count, and
    because they share the same per-clan fetches - once a clan's war is warm,
    the marginal cost of the other sections is near zero.
    """
    if force:
        todo_data.cache_drop_prefix("player:")
        todo_data.cache_drop_prefix("war:")
        todo_data.cache_drop_prefix("cwl:")
        todo_data.cache_drop_prefix(f"links:{discord_id}")

    cache_key = f"links:{discord_id}"
    tags = todo_data.cache_get(cache_key)
    if tags is None:
        tags = await resolve_tags(discord_id)
        if tags is None:
            # Lookup FAILED. Not the same as having no accounts, and the user
            # must not be sent off to fix a problem they do not have.
            return None, _notice(
                "Couldn't reach the link service",
                "The Clash↔Discord link service didn't answer, so I can't tell "
                "which accounts are yours.\n\n"
                "This is a problem on their end, not yours — try again shortly.",
            )
        todo_data.cache_put(cache_key, tags, todo_data.TTL_LINKS)

    if not tags:
        return None, _notice(
            "No linked accounts",
            "I couldn't find any Clash of Clans accounts linked to your Discord.\n\n"
            "Link one with ClashKing's `/link` command (you'll need your in-game "
            "API token from **Settings → More Settings → API Token**), then run "
            "`/todo` again.",
        )

    accounts, errors = await todo_data.fetch_accounts(coc_client, tags)
    if not accounts:
        return None, _notice(
            "Couldn't load your accounts",
            "Your accounts are linked, but the Clash API didn't answer for any "
            "of them. Try again shortly.",
        )

    war = await todo_data.build_war_view(coc_client, accounts)
    cwl = await todo_data.build_cwl_view(coc_client, accounts)
    if errors:
        print(f"[todo] {len(errors)} account lookups failed for {discord_id}: {errors[:5]}")

    return {VIEW_WAR: war, VIEW_CWL: cwl, VIEW_RAID: None}, None


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

@loader.command
class Todo(
    lightbulb.SlashCommand,
    name="todo",
    description="What your linked Clash accounts still need to do",
):
    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            bot: hikari.GatewayBot = lightbulb.di.INJECTED,
            coc_client: coc.Client = lightbulb.di.INJECTED,
            mongo: MongoClient = lightbulb.di.INJECTED,
    ) -> None:
        # Ephemeral in a guild, persistent in a DM. A DM dashboard is meant to
        # be scrolled back to; an in-channel one is a convenience read.
        await ctx.defer(ephemeral=ctx.guild_id is not None)

        data, problem = await _load(bot, coc_client, ctx.user.id)
        await ctx.respond(components=problem if problem else render_dashboard(VIEW_WAR, 0, data))


# ---------------------------------------------------------------------------
# View handlers
#
# Every parameter that could come from stored state is defaulted, and none is
# read. The dispatcher's button_store lookup always misses for /todo - that is
# the design - so a handler must be callable with only ctx and action_id.
# ---------------------------------------------------------------------------

async def _switch(ctx, view: str, action_id: str, coc_client, bot, force: bool = False) -> list:
    try:
        page = int(action_id.split("|")[-1])
    except (TypeError, ValueError):
        page = 0
    data, problem = await _load(bot, coc_client, ctx.user.id, force=force)
    return problem if problem else render_dashboard(view, page, data)


@register_action("todo_war")
@lightbulb.di.with_di
async def todo_war(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    return await _switch(ctx, VIEW_WAR, action_id, coc_client, bot)


@register_action("todo_cwl")
@lightbulb.di.with_di
async def todo_cwl(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    return await _switch(ctx, VIEW_CWL, action_id, coc_client, bot)


@register_action("todo_raid")
@lightbulb.di.with_di
async def todo_raid(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        **kwargs,
) -> list:
    # Registered so the button is never an unknown action, but phase 3 (the
    # roster diff) is not built. The button ships disabled; this is the guard
    # for an older panel whose button was not.
    return _notice(
        "Raids aren't ready yet",
        "The raid weekend view is still being built. War and CWL work now.",
    )


@register_action("todo_refresh")
@lightbulb.di.with_di
async def todo_refresh(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "war|0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    view = action_id.split("|")[0] if action_id else VIEW_WAR
    if view not in (VIEW_WAR, VIEW_CWL, VIEW_RAID):
        view = VIEW_WAR
    return await _switch(ctx, view, action_id, coc_client, bot, force=True)
