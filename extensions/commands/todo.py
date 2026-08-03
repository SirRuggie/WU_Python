"""/todo - what each of your linked Clash accounts still owes.

DM-first. Three views (war hits, CWL hits, raids) switched by a select menu;
only ACTIONABLE accounts appear. See docs/todo-dashboard-proposal.md.

LAYOUT RULES, all of them from observed mobile rendering rather than theory:

  NOTHING MAY WRAP AT PHONE WIDTH. Budget ~28 characters per line. The first
  version's clan headers ("CLAN · prep · opens in 18 hours · closes in 2 days")
  wrapped to two lines for every clan.

  <t:N:R> AND `backticks` RENDER AS GREY CHIPS, not text. Mid-sentence they
  shatter a line into disconnected fragments, and a chip whose x-position
  depends on the name before it destroys vertical alignment. Timestamps get
  their own line; counts lead the row and carry no backticks.

  TIMING IS STATED ONCE PER BLOCK, not once per clan. Grouping is by TIME
  first (Live / Opens) and clan second, because time is what varies.

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

  TH EMOJI COME FROM utils.emoji. TH_EMOJI is built with getattr/hasattr so a
  missing level degrades to no emoji rather than an AttributeError inside a
  render path.
"""

import time

import coc
import lightbulb
import hikari

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SectionComponentBuilder as Section,
    SelectOptionBuilder as SelectOption,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
    TextSelectMenuBuilder as TextSelectMenu,
    ThumbnailComponentBuilder as Thumbnail,
)

from extensions.components import register_action
from utils import todo_data
from utils.clash_links import resolve_tags
from utils.constants import BLUE_ACCENT, GOLD_ACCENT, RED_ACCENT
from utils.emoji import emojis
from utils.mongo import MongoClient

loader = lightbulb.Loader()

PAGE_SIZE = 20
VIEW_WAR = "war"
VIEW_CWL = "cwl"
VIEW_RAID = "raid"

VIEW_LABEL = {VIEW_WAR: "War", VIEW_CWL: "CWL", VIEW_RAID: "Raids"}
VIEW_ORDER = (VIEW_WAR, VIEW_CWL, VIEW_RAID)

CACHE_LOGOS = "clanlogos"
TTL_LOGOS = 60 * 60   # family clan list changes rarely; a logo upload is rarer

# Real TH emoji from utils.emoji rather than the text "TH17". Custom emoji are
# ~28 chars of markup but render one character wide, so the LINE gets shorter
# while the character budget barely moves (10 rows = ~280 of 4000).
TH_EMOJI = {
    level: str(getattr(emojis, f"TH{level}"))
    for level in range(2, 19)
    if hasattr(emojis, f"TH{level}")
}


def _emoji(name: str) -> str:
    """Markup for a named custom emoji, or "" if it is not defined.

    Same safety as TH_EMOJI: a renamed or removed attribute degrades to nothing
    rather than raising inside a render path or printing raw markup in a row.
    str() preserves the "<a:" prefix on animated emoji, which is required -
    dropping it renders the emoji broken.
    """
    obj = getattr(emojis, name, None)
    return str(obj) if obj is not None else ""


def _partial(name: str):
    """A CustomEmoji for a component's `emoji=` field, or UNDEFINED.

    Components need a real emoji object, not markup. EmojiType.partial_emoji
    RAISES ValueError on a malformed id, so a bad id must be caught here or it
    takes the whole panel down.
    """
    obj = getattr(emojis, name, None)
    if obj is None:
        return hikari.UNDEFINED
    try:
        return obj.partial_emoji
    except (ValueError, IndexError):
        return hikari.UNDEFINED


# One emoji per view, used in the header AND the nav option so they match.
VIEW_EMOJI = {VIEW_WAR: "War", VIEW_CWL: "CWL", VIEW_RAID: "RaidMedals"}

# Timing blocks. Live is animated on purpose - it is the single most important
# distinction on the panel: can I attack right now, or am I waiting?
EMOJI_LIVE = "sword_fighting"
EMOJI_WAITING = "Waiting"

# Unicode slots. Chosen for meaning, not decoration - see the report.
U_REFRESH = "🔄"      # reload, reads as an action rather than a destination
U_URGENT = "⏰"       # pairs with the red accent when something closes < 2h
U_CAUGHT_UP = "✨"    # positive without being a checkmark ("done" != "nothing to do")
# 🔒 (private war log) and ⚠️ (lookup failed) live in todo_data.py, inline in
# the notes they belong to - that module builds them and cannot import from here.


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _panel(body_components: list, accent=RED_ACCENT) -> list:
    return [Container(accent_color=accent, components=body_components)]


def _urgency_accent(view_data):
    """Colour the container by time pressure, so the accent bar MEANS something.

    This is the answer to "what should the colours mean". Discord styles encode
    consequence, not category - colouring by which tab you are on is arbitrary,
    because the label already says that. Colouring by deadline is information
    you cannot get any other way at a glance.

        RED    something closes within 2 hours
        GOLD   something closes within 12 hours
        BLUE   everything else, including prep-only and empty views
    """
    if view_data is None or not getattr(view_data, "ok", False) or not view_data.rows:
        return BLUE_ACCENT
    soonest = [r.ends_at for r in view_data.rows if r.state != "preparation" and r.ends_at]
    if not soonest:
        return BLUE_ACCENT
    remaining = min(soonest) - int(time.time())
    if remaining <= 2 * 60 * 60:
        return RED_ACCENT
    if remaining <= 12 * 60 * 60:
        return GOLD_ACCENT
    return BLUE_ACCENT


def _notice(title: str, body: str) -> list:
    """A single-message panel. Used for every state that is not a dashboard."""
    return _panel([
        Text(content=f"## {title}"),
        Separator(divider=True),
        Text(content=body),
        Media(items=[MediaItem(media="assets/Red_Footer.png")]),
    ])


def _nav_select(view: str, counts: dict) -> ActionRow:
    """House-style navigation: a TextSelectMenu, not a row of coloured buttons.

    clan/dashboard/dashboard.py navigates with a select whose options carry an
    emoji and a description. That is strictly more informative than buttons -
    every section's status is visible without clicking - and it is why the old
    button row read as a different product from the rest of the bot.

    Deliberately NOT registered with group=. The group mechanism requires each
    option's `value` to BE a registered action name, so it cannot carry a page
    number. This is a plain action that reads ctx.interaction.values[0] itself.
    """
    def describe(key: str) -> str:
        value = counts.get(key)
        if value is None:
            return "couldn't be read — try Refresh"
        if value == 0:
            return "nothing outstanding"
        return f"{value} account(s) owe attacks"

    options = [
        SelectOption(
            label=f"{VIEW_LABEL[VIEW_WAR]} Hits",
            description=describe(VIEW_WAR),
            value=VIEW_WAR,
            emoji=_partial(VIEW_EMOJI[VIEW_WAR]),
            is_default=view == VIEW_WAR,
        ),
        SelectOption(
            label=VIEW_LABEL[VIEW_CWL],
            description=describe(VIEW_CWL),
            value=VIEW_CWL,
            emoji=_partial(VIEW_EMOJI[VIEW_CWL]),
            is_default=view == VIEW_CWL,
        ),
        SelectOption(
            label=VIEW_LABEL[VIEW_RAID],
            description="not available yet",
            value=VIEW_RAID,
            emoji=_partial(VIEW_EMOJI[VIEW_RAID]),
            is_default=view == VIEW_RAID,
        ),
        SelectOption(
            label="Refresh",
            description="re-check everything now",
            value="refresh",
            emoji=U_REFRESH,
        ),
    ]
    return ActionRow(components=[
        TextSelectMenu(
            max_values=1,
            custom_id=f"todo_nav:{view}",
            placeholder="Switch view…",
            options=options,
        )
    ])


def _clan_logos() -> dict:
    """{clan_tag: logo_url} for family clans, from the clan_data collection.

    These are OUR Cloudinary logos, uploaded via /clan upload and rendered the
    same way at update_clan_info.py:465. The Clash API badge is the generic
    war-league shield - every clan in a league looks identical - so it is only
    a fallback for clans outside the family.

    Read from the shared cache rather than threaded through six signatures.
    _load populates it; a miss just means every clan falls back to its badge.
    """
    return todo_data.cache_get(CACHE_LOGOS) or {}


def _thumbnail_for(row):
    """Our logo if the clan is one of ours, else the Clash badge, else nothing."""
    logo = _clan_logos().get(row.clan_tag)
    if logo and isinstance(logo, str) and logo.startswith("http"):
        return logo
    return row.clan_badge


def _row_line(row) -> str:
    """One account, one line, never wrapping on a phone.

    THE COUNT LEADS. It is fixed-width, so every row's left edge lines up.
    Putting it after the name (as the first version did) meant the count landed
    at a different x-position on every row and nothing aligned vertically.

    NO BACKTICKS. Discord renders inline code as a grey chip, so `0/1` became a
    second floating box per row - the other half of the alignment problem.

    The TH emoji replaces the text "TH17": shorter on the line, and a per-row
    visual anchor, which is what this layout is for.
    """
    th = TH_EMOJI.get(row.town_hall, "")
    lead = f"{row.used}/{row.limit}"
    return f"{lead} {th} {row.account}".replace("  ", " ").strip()


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
        first = members[0]
        lines = "\n".join(_row_line(r) for r in members)
        body = f"**{first.clan_name}**\n{lines}"

        # Section + Thumbnail(clan badge). The badge is the visual anchor that
        # the old "🕒 CLAN · prep · opens in 18h · closes in 2 days" header was
        # trying and failing to be - that header wrapped to two lines on a phone
        # for every single clan. The clan name now sits alone on a short line
        # and the timing has moved out to a block heading above, stated once.
        thumb = _thumbnail_for(first)
        if thumb:
            out.append(Section(
                accessory=Thumbnail(media=thumb),
                components=[Text(content=body)],
            ))
        else:
            out.append(Text(content=body))

        if index != len(order) - 1:
            out.append(Separator(divider=False, spacing=hikari.SpacingType.SMALL))
    return out


def _timing_blocks(rows: list) -> list:
    """Rows split into timing blocks, each stating its deadline ONCE.

    The old layout repeated "prep · opens · closes" on every clan header - three
    clans meant the same three words three times. The thing that actually varies
    and matters is TIME, not clan, so time is the outer grouping now.

    Each block puts its timestamp ALONE on its own line. <t:N:R> renders as a
    grey chip, so mid-sentence it chops a heading into disconnected fragments;
    on its own line the chip reads as deliberate.
    """
    live = [r for r in rows if r.state != "preparation"]
    prep = [r for r in rows if r.state == "preparation"]

    out: list = []
    for emoji_name, label, group, stamp_of in (
        (EMOJI_LIVE, "Live · closes", live, lambda r: r.ends_at),
        (EMOJI_WAITING, "Opens", prep, lambda r: r.starts_at),
    ):
        if not group:
            continue
        if out:
            out.append(Separator(divider=True, spacing=hikari.SpacingType.SMALL))
        heading = f"{_emoji(emoji_name)} **{label}**".strip()
        out.append(Text(content=heading))
        stamps = [s for s in (stamp_of(r) for r in group) if s]
        if stamps:
            out.append(Text(content=f"<t:{min(stamps)}:R>"))
        out.extend(_render_rows(group))
    return out


def render_dashboard(view: str, page: int, data: dict) -> list:
    """The dashboard itself.

    `data` maps view name -> ViewData. A view whose ViewData is None could not
    be computed at all.
    """
    counts = {k: (v.count if v is not None and v.ok else None) for k, v in data.items()}
    current = data.get(view)

    # Title carries the count so the header line does one more job. "###" not
    # "##" - the house style uses H3 - and NO trailing blank line, which was
    # dead vertical space at the top of every panel.
    outstanding = counts.get(view)
    title = f"### {_emoji(VIEW_EMOJI.get(view, ''))} {VIEW_LABEL[view]}".replace("###  ", "### ")
    if outstanding:
        title += f" · {outstanding} to do"
        if _urgency_accent(current) == RED_ACCENT:
            title += f" {U_URGENT}"
    body: list = [Text(content=title)]

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
            # "All caught up" is a verdict on the WHOLE dashboard, so it may
            # only be said when every section is empty. Saying it per-view told
            # a user with three pending CWL hits that there was nothing to do,
            # because the default view happened to be the empty one.
            elsewhere = [
                VIEW_LABEL[k] for k, v in data.items()
                if k != view and v is not None and v.ok and v.count
            ]
            if elsewhere:
                body.append(Text(content=(
                    f"**Nothing due in {VIEW_LABEL[view]}.**\n"
                    f"-# Still to do in: {', '.join(elsewhere)}"
                )))
            else:
                body.append(Text(content=f"{U_CAUGHT_UP} **All caught up.**"))
        else:
            body.extend(_timing_blocks(window))

        if current.notes:
            body.append(Separator(divider=True))
            body.append(Text(content="\n".join(f"-# {n}" for n in current.notes)))

    body.append(Separator(divider=True, spacing=hikari.SpacingType.LARGE))
    body.append(_nav_select(view, counts))

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

    # Media footer stays - it is house style on every panel in the repo. The
    # "Data via ClashKing" TEXT line above it is gone.
    body.append(Media(items=[MediaItem(media="assets/Red_Footer.png")]))
    return _panel(body, _urgency_accent(current))


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

async def _load_clan_logos(mongo) -> None:
    """Populate the family-clan logo map, once per TTL.

    Projection-only and read-only. A failure here is cosmetic - clans fall back
    to their Clash badge - so it must never take the dashboard down.
    """
    if todo_data.cache_get(CACHE_LOGOS) is not None:
        return
    try:
        docs = await mongo.clans.find({}, {"tag": 1, "logo": 1}).to_list(length=None)
    except Exception as exc:  # noqa: BLE001
        print(f"[todo] clan logo lookup failed: {type(exc).__name__}: {exc}")
        todo_data.cache_put(CACHE_LOGOS, {}, 60)
        return
    logos = {d.get("tag"): d.get("logo") for d in docs if d.get("tag") and d.get("logo")}
    todo_data._d(f"_load_clan_logos loaded {len(logos)} logos of {len(docs)} clans")
    todo_data.cache_put(CACHE_LOGOS, logos, TTL_LOGOS)


async def _load(bot, coc_client, discord_id: int, force: bool = False, mongo=None):
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
        todo_data.cache_drop_prefix(CACHE_LOGOS)

    if mongo is not None:
        await _load_clan_logos(mongo)

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

    todo_data._d(f"_load resolved tags={len(tags)} accounts={len(accounts)} "
                 f"errors={len(errors)} client={type(coc_client).__name__}")
    war = await todo_data.build_war_view(coc_client, accounts)
    todo_data._d(f"_load war view built rows={war.count} ok={war.ok}")
    todo_data._d("_load about to build CWL view")
    cwl = await todo_data.build_cwl_view(coc_client, accounts)
    todo_data._d(f"_load cwl view built rows={cwl.count} ok={cwl.ok}")
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

        data, problem = await _load(bot, coc_client, ctx.user.id, mongo=mongo)
        if problem:
            await ctx.respond(components=problem)
            return
        # Open on the first view that actually has work. Always opening on War
        # meant a user whose only pending hits were CWL saw an empty War view
        # and read it as the whole dashboard's verdict.
        opening = next(
            (v for v in VIEW_ORDER
             if data.get(v) is not None and data[v].ok and data[v].count),
            VIEW_WAR,
        )
        await ctx.respond(components=render_dashboard(opening, 0, data))


# ---------------------------------------------------------------------------
# View handlers
#
# Every parameter that could come from stored state is defaulted, and none is
# read. The dispatcher's button_store lookup always misses for /todo - that is
# the design - so a handler must be callable with only ctx and action_id.
# ---------------------------------------------------------------------------

async def _switch(ctx, view: str, action_id: str, coc_client, bot, force: bool = False, mongo=None) -> list:
    try:
        page = int(action_id.split("|")[-1])
    except (TypeError, ValueError):
        page = 0
    data, problem = await _load(bot, coc_client, ctx.user.id, force=force, mongo=mongo)
    return problem if problem else render_dashboard(view, page, data)


@register_action("todo_war")
@lightbulb.di.with_di
async def todo_war(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    return await _switch(ctx, VIEW_WAR, action_id, coc_client, bot, mongo=mongo)


@register_action("todo_cwl")
@lightbulb.di.with_di
async def todo_cwl(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    return await _switch(ctx, VIEW_CWL, action_id, coc_client, bot, mongo=mongo)


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


@register_action("todo_nav")
@lightbulb.di.with_di
async def todo_nav(
        ctx: lightbulb.components.MenuContext,
        action_id: str = VIEW_WAR,
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    """The select-menu router.

    Registered WITHOUT group=, so the dispatcher does not try to resolve the
    selected value as an action name - it reads values[0] here instead. That is
    what lets an option carry "refresh" as well as a view name.
    """
    values = getattr(ctx.interaction, "values", None) or []
    choice = values[0] if values else action_id
    if choice == "refresh":
        return await _switch(ctx, action_id or VIEW_WAR, "0", coc_client, bot, force=True, mongo=mongo)
    if choice not in VIEW_ORDER:
        choice = VIEW_WAR
    if choice == VIEW_RAID:
        return _notice(
            "Raids aren't ready yet",
            "The raid weekend view is still being built. War and CWL work now.",
        )
    return await _switch(ctx, choice, "0", coc_client, bot, mongo=mongo)


@register_action("todo_refresh")
@lightbulb.di.with_di
async def todo_refresh(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "war|0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> list:
    view = action_id.split("|")[0] if action_id else VIEW_WAR
    if view not in (VIEW_WAR, VIEW_CWL, VIEW_RAID):
        view = VIEW_WAR
    return await _switch(ctx, view, action_id, coc_client, bot, force=True, mongo=mongo)
