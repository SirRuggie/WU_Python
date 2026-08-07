"""/todo - what each of your linked Clash accounts still owes.

DM-first. Three views (war hits, CWL hits, raids) switched by a select menu;
only ACTIONABLE accounts appear. See docs/todo-dashboard-proposal.md.

LAYOUT RULES, all of them from observed mobile rendering rather than theory:

  NOTHING MAY WRAP AT PHONE WIDTH. Budget ~28 characters per line. The first
  version's clan headers ("CLAN · prep · opens in 18 hours · closes in 2 days")
  wrapped to two lines for every clan.

  <t:N:R> AND `backticks` RENDER AS GREY CHIPS, not text. A chip is fine at the
  END of a SHORT line - "Battle Day · ends in 5 hours" reads as one sentence.
  It only shatters a line when the line is long enough to wrap, which is what
  the first version's clan headers did. Row counts still lead and carry no
  backticks: there a chip's x-position depended on the name before it, which
  destroyed vertical alignment.

  GROUPING IS BY STATE, TIMING IS PER CLAN. A block heading says only what is
  true of every row under it - Battle Day, Prep Day - because the deadline is
  NOT: two clans in one Prep Day block were 9h29m and 3h51m from battle day,
  and a min() heading claimed "starts in 4 hours" over both. Each clan states
  its own deadline on a subtext line under its name.

  FOUR TYPE SIZES, one per level of the hierarchy: "##" panel title, "###"
  block heading, "**bold**" clan name, plain text row. Everything below the
  title used to be bold, so the panel had no visible hierarchy at all.

Design rules enforced here, each of which cost real investigation to establish:

  ONE COLON in every custom_id. The dispatcher splits at the FIRST colon and
  everything after it is the state key, so `action:{id}:{page}` makes the state
  key a composite that misses the lookup. manage_roles.py:366 does exactly that
  and its pagination has never worked. View lives in the action name, page in
  the action_id, and nothing else.

  STATELESS COMPONENT ROUTING. Page comes from the custom_id and user identity
  from ctx.user.id on the interaction. Mongo-backed history may contribute
  data, but no evictable component-state document controls the panel. The
  dispatcher's state lookup can miss safely because every handler defaults its
  parameters and reads action_id.

  DM auto-refresh reads todo_sessions in the background. Interaction ROUTING
  remains stateless, while rendering normally reuses the bounded snapshot that
  produced that exact message. Page still comes from the custom_id and user
  identity from the click; a snapshot miss simply reloads, so an old panel
  still works after eviction or a process restart.

  NO ctx.guild_id. It is None in a DM, and the house header pattern
  (clan/dashboard/dashboard.py:44 -> bot.cache.get_guild(ctx.guild_id)
  .make_icon_url()) raises AttributeError there. ctx.member is None too, so no
  role checks anywhere in this file.

  TH EMOJI COME FROM utils.emoji. TH_EMOJI is built with getattr/hasattr so a
  missing level degrades to no emoji rather than an AttributeError inside a
  render path.
"""

import asyncio
import contextlib
import time
import weakref
from collections import OrderedDict
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

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
from utils import clan_history, coc_maintenance, todo_data, todo_sessions
from utils.clash_links import resolve_tags
from utils.constants import BLUE_ACCENT, GOLD_ACCENT, RED_ACCENT
from utils.emoji import emojis
from utils.mongo import MongoClient

loader = lightbulb.Loader()

_auto_refresh_task: asyncio.Task | None = None
_refresh_locks: weakref.WeakValueDictionary[str, asyncio.Lock] = (
    weakref.WeakValueDictionary()
)

# Keep the complete four-view result that was used to render each live panel.
# Component routing remains stateless: a cache miss still performs the normal
# load, so old messages and process restarts keep working. Count and age bounds
# keep abandoned Discord messages from retaining account data indefinitely.
PANEL_SNAPSHOT_LIMIT = 512
PANEL_SNAPSHOT_TTL_SECONDS = todo_sessions.TTL_SECONDS


@dataclass(frozen=True)
class _DashboardSnapshot:
    data: dict[str, todo_data.ViewData] | None
    problem: list | None
    checked_at: int
    stored_at: float


_panel_snapshots: OrderedDict[
    tuple[int, int, int], _DashboardSnapshot
] = OrderedDict()


def _snapshot_key(
    user_id: int, channel_id: int, message_id: int
) -> tuple[int, int, int] | None:
    key = (int(user_id), int(channel_id), int(message_id))
    return key if all(key) else None


def _snapshot_get(
    user_id: int, channel_id: int, message_id: int
) -> _DashboardSnapshot | None:
    key = _snapshot_key(user_id, channel_id, message_id)
    if key is None:
        return None
    now = time.monotonic()
    _snapshot_prune(now)
    snapshot = _panel_snapshots.get(key)
    if snapshot is None:
        return None
    _panel_snapshots.move_to_end(key)
    return snapshot


def _snapshot_prune(observed_at: float | None = None) -> None:
    """Remove age-expired snapshots; the scheduler calls this every minute."""
    now = time.monotonic() if observed_at is None else float(observed_at)
    for key, snapshot in tuple(_panel_snapshots.items()):
        if now - snapshot.stored_at >= PANEL_SNAPSHOT_TTL_SECONDS:
            _panel_snapshots.pop(key, None)


def _snapshot_put(
    user_id: int,
    channel_id: int,
    message_id: int,
    data: dict[str, todo_data.ViewData] | None,
    problem: list | None,
    checked_at: int,
) -> None:
    key = _snapshot_key(user_id, channel_id, message_id)
    if key is None or (data is None and problem is None):
        return
    _snapshot_prune()
    _panel_snapshots[key] = _DashboardSnapshot(
        data, problem, int(checked_at), time.monotonic()
    )
    _panel_snapshots.move_to_end(key)
    while len(_panel_snapshots) > PANEL_SNAPSHOT_LIMIT:
        _panel_snapshots.popitem(last=False)


def _snapshot_drop(user_id: int, channel_id: int, message_id: int) -> None:
    key = _snapshot_key(user_id, channel_id, message_id)
    if key is not None:
        _panel_snapshots.pop(key, None)


def _refresh_lock(owner_id: str) -> asyncio.Lock:
    """One lock through the actual Discord edit; weak storage needs no cleanup."""
    lock = _refresh_locks.get(owner_id)
    if lock is None:
        lock = asyncio.Lock()
        _refresh_locks[owner_id] = lock
    return lock

# ---------------------------------------------------------------------------
# THE COMPONENT BUDGET. This is what pages are measured in - NOT rows.
#
# PAGE_SIZE = 20 used to live here and it capped the wrong thing. Rows are
# nearly free; CLANS are expensive. A user with 2 clans and 8 rows rendered 19
# components and worked; a user with 34 clans rendered ~91 on his first screen
# and Discord rejected the entire message with
#   400 (50035) Invalid Form Body: components - Total number of components
#   cannot exceed 40
# That was the ORIGINAL /todo failure, and it presented as "spins and never
# returns" because a 400 leaves no panel and no visible error.
#
# 40 is Discord's hard cap and it counts NESTED children - our payload has
# exactly one top-level component, the Container, so a top-level-only count
# could never exceed 1. The 400 is the oracle.
COMPONENT_LIMIT = 40

# Headroom below the cap. Not superstition: it is what absorbs one more Text
# being added to the panel by someone who does not recompute PANEL_FIXED.
COMPONENT_HEADROOM = 2
COMPONENT_BUDGET = COMPONENT_LIMIT - COMPONENT_HEADROOM   # 38

# Panel furniture that is on every page regardless of content:
#   Container 1 + title Text 1 + Separator 1 + _nav_block 7
# _nav_block is Separator + (ActionRow + select) + Media + Text + (ActionRow +
# button) = 7, counting nested children.
PANEL_FIXED = 10

# RESERVED, NEVER CONDITIONAL. Notes render on every page when the view has
# any, and the pagination row appears only when pages > 1 - so budgeting for it
# only once paginated is circular: the act of paginating would push page 1 back
# over the limit. Both are always assumed present.
RESERVE_NOTES = 2          # Separator + Text
RESERVE_PAGINATION = 4     # ActionRow + 3 Buttons

VIEW_WAR = "war"
VIEW_CWL = "cwl"
VIEW_RAID = "raid"

VIEW_PRIVATE = "private"

VIEW_LABEL = {
    VIEW_WAR: "War",
    VIEW_CWL: "CWL",
    VIEW_RAID: "Raids",
    VIEW_PRIVATE: "Private War Logs",
}
VIEW_ORDER = (VIEW_WAR, VIEW_CWL, VIEW_RAID, VIEW_PRIVATE)

# Views eligible to be the landing view. Private War Logs is DELIBERATELY not
# here: its count is usually the largest number on the panel, and it is not
# work - it is a list of conversations to have with clan leaders. Landing there
# would bury the attacks the dashboard exists to surface.
VIEW_OPENING_ORDER = (VIEW_WAR, VIEW_CWL, VIEW_RAID)

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

# Views with no custom emoji fall back to unicode here.
VIEW_UNICODE = {VIEW_PRIVATE: "🔒"}

# Timing blocks. Live is animated on purpose - it is the single most important
# distinction on the panel: can I attack right now, or am I waiting?
EMOJI_LIVE = "sword_fighting"
EMOJI_WAITING = "Waiting"

# Block headings, per view. "Opens" alone was a bare verb that named no state -
# it told you an event was happening without saying WHICH. These name the game
# state, and NOTHING ELSE: the heading once carried "· ends" plus a timestamp,
# which made it assert a deadline over clans it was not true for. The verb and
# the clock now live on each clan's own subtext line, as "ends in 5 hours".
#
# Each entry is (live label, prep label). The prep half never fires for raids -
# raid Rows carry the default state "inWar" - but it is spelled out rather than
# left to a fallback so a future prep-capable raid row cannot render "Prep Day"
# for a raid weekend.
BLOCK_LABELS = {
    VIEW_WAR:  ("Battle Day", "Prep Day"),
    VIEW_CWL:  ("Battle Day", "Prep Day"),
    VIEW_RAID: ("Raid Weekend", "Raid Weekend"),
}
BLOCK_LABELS_DEFAULT = ("Live", "Waiting")

# Unicode slots. Chosen for meaning, not decoration - see the report.
U_REFRESH = "🔄"      # reload, reads as an action rather than a destination
U_URGENT = "⏰"       # pairs with the red accent when something closes < 2h
U_CAUGHT_UP = "✨"    # positive without being a checkmark ("done" != "nothing to do")
U_PRIVATE = "🔒"      # can't look, as distinct from nothing to see
U_FAILED = "⚠️"       # couldn't read, deliberately unlike the padlock
U_MAINTENANCE = "🔧"  # the game is down, as distinct from we couldn't read it
# The same two glyphs also appear inline in todo_data.py's note strings - that
# module builds those notes and cannot import from here.


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _panel(body_components: list, accent=RED_ACCENT) -> list:
    return [Container(accent_color=accent, components=body_components)]


def _manual_fallback_panel(components: list, *, checked_at: int | None = None) -> list:
    """Copy a panel with a concise footer that promises no scheduler."""
    checked_at = int(checked_at if checked_at is not None else time.time())
    manual_status = Text(content=(
        f"-# Checked <t:{checked_at}:R> · Use Check now to update"
    ))
    rebuilt = []
    for container in components:
        children = []
        replaced = False
        for child in container.components:
            content = getattr(child, "content", None)
            if isinstance(content, str) and content.startswith("-# Checked "):
                children.append(manual_status)
                replaced = True
            else:
                children.append(child)
        rebuilt.append(Container(
            id=container.id,
            accent_color=container.accent_color,
            spoiler=container.is_spoiler,
            components=children,
        ))
        if not replaced:
            print("[todo] WARNING: fallback panel had no freshness footer")
    return rebuilt


def _automatic_status_panel(
    components: list,
    *,
    checked_at: int,
    refresh_until: datetime,
) -> list:
    """Copy a panel with the exact persisted automatic-check deadline."""
    # AsyncMongoClient returns BSON UTC datetimes without tzinfo unless the
    # client is configured tz_aware. Treat naive values as UTC, never as this
    # host's local timezone (which would shift Discord's timestamp by 4–5h).
    if refresh_until.tzinfo is None:
        refresh_until = refresh_until.replace(tzinfo=timezone.utc)
    else:
        refresh_until = refresh_until.astimezone(timezone.utc)
    status = Text(content=(
        f"-# Checked <t:{int(checked_at)}:R> · Rechecks about every "
        f"{todo_sessions.REFRESH_INTERVAL_SECONDS // 60} min · "
        f"Stops <t:{int(refresh_until.timestamp())}:R>"
    ))
    rebuilt = []
    for container in components:
        children = []
        replaced = False
        for child in container.components:
            content = getattr(child, "content", None)
            if isinstance(content, str) and content.startswith("-# Checked "):
                children.append(status)
                replaced = True
            else:
                children.append(child)
        rebuilt.append(Container(
            id=container.id,
            accent_color=container.accent_color,
            spoiler=container.is_spoiler,
            components=children,
        ))
        if not replaced:
            print("[todo] WARNING: automatic panel had no freshness footer")
    return rebuilt


def _retired_panel() -> list:
    """Small truthful replacement for a superseded automatic panel."""
    return _panel([
        Text(content="## To-do panel"),
        Text(content="Use Check now to update this panel and make it automatic."),
        Separator(divider=True, spacing=hikari.SpacingType.LARGE),
        Text(content="-# Only one DM panel updates automatically"),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"todo_refresh:{VIEW_WAR}|0",
                emoji=_partial("refresh") or U_REFRESH,
                label="Check now",
            ),
        ]),
    ], BLUE_ACCENT)


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


def _notice(title: str, body: str, view: str = VIEW_WAR, counts: dict | None = None,
            *, checked_at: int | None = None, auto_refresh: bool = False,
            refresh_until: datetime | None = None) -> list:
    """A panel for every state that is not a dashboard.

    IT STILL CARRIES THE NAV. A state that renders correctly and leaves the user
    with no way out is a dead end - they have to re-run /todo to escape. Every
    panel this module produces keeps the select menu and the refresh button, and
    on an error state Check now is precisely the button they want.
    """
    return _panel([
        # "##" to match the dashboard's panel title - a notice IS the panel.
        Text(content=f"## {title}"),
        Separator(divider=True),
        Text(content=body),
        # _nav_block ends with the footer and the freshness row - do not append
        # a second Media here.
        *_nav_block(
            view, counts or {}, checked_at=checked_at, auto_refresh=auto_refresh,
            refresh_until=refresh_until,
        ),
    ])


def _nav_block(view: str, counts: dict, pager=None, *,
               unchecked: set[str] | None = None,
               unavailable: dict[str, str] | None = None,
               checked_at: int | None = None,
               auto_refresh: bool = False,
               refresh_until: datetime | None = None) -> list:
    """Separator, the view select, optional pagination, then the freshness line.

    THE ONLY PLACE NAVIGATION IS BUILT. Every panel state calls this, so a new
    state cannot ship without a way out.

    `pager` is the page ◀ / N of M / ▶ ActionRow, or None. It goes BETWEEN the
    view select and the red footer, because it pages the content above it - not
    below the footer beside Refresh, which is where it sat half-built and
    unrendered while PAGE_SIZE made `pages > 1` unreachable.

    LAYOUT: check status, then the Check now button on its own ActionRow.

    THE BUTTON WAS A SECTION ACCESSORY AND THAT DOES NOT WORK ON A PHONE. On
    desktop it rendered as intended - "updated 7 minutes ago  [refresh]", one
    row. On mobile the accessory dropped to its own line under the text and
    read as stranded, which is the exact problem the accessory was chosen to
    solve. Mobile is the primary venue, so the desktop-only win loses.

    Since a narrow accessory wraps to its own line ANYWAY, it is put there
    deliberately, in an ActionRow, and given a LABEL. That is the part that
    stops it looking stranded: a bare icon sitting alone reads as leftover, a
    labelled "Check now" button reads as a control. Same two lines on mobile as
    the accessory produced, but composed rather than collapsed - and now
    identical on both platforms instead of good on one and broken on the other.

    The two obvious alternatives are both structurally impossible in Components
    V2, so do not try them again:
      - select and button in one ActionRow: a row holds EITHER up to 5 buttons
        OR exactly one select, never a mix.
      - select inside a Section: SectionBuilderComponentsT is TextDisplay only.

    Check now is a button rather than a select option because the select lists
    places you can GO; checking is something you DO to where you already are.
    """
    # This reports the successful dashboard check, not the oldest entry in the
    # process-wide cache. The old global timestamp could belong to an unrelated
    # user's clan and therefore was not a truthful timestamp for this panel.
    checked_at = int(checked_at if checked_at is not None else time.time())
    if auto_refresh:
        until = refresh_until or todo_sessions.new_refresh_until()
        if until.tzinfo is None:
            until = until.replace(tzinfo=timezone.utc)
        stamp = (
            f"-# Checked <t:{checked_at}:R> · Rechecks about every "
            f"{todo_sessions.REFRESH_INTERVAL_SECONDS // 60} min · "
            f"Stops <t:{int(until.timestamp())}:R>"
        )
    else:
        stamp = f"-# Checked <t:{checked_at}:R> · DM /todo for auto-checks"

    return [
        Separator(divider=True, spacing=hikari.SpacingType.LARGE),
        _nav_select(
            view, counts, unchecked=unchecked, unavailable=unavailable
        ),
        # Pagination, when there is more than one page. Above the footer, below
        # the view select - it belongs to the content, not to the caption row.
        *([pager] if pager is not None else []),
        # The Media footer sits ABOVE the freshness row, not at the very bottom
        # as it does on every other panel in the repo. Deliberate: the red line
        # then reads as the rule that closes the dashboard, with the freshness
        # stamp and its refresh button sitting under it as a caption.
        #
        # Done by reordering INSIDE the container rather than moving anything
        # out to top level. A top-level component renders outside the accent bar
        # and would lose the coloured stripe, detaching the row from the panel.
        Media(items=[MediaItem(media="assets/Red_Footer.png")]),
        Text(content=stamp),
        ActionRow(components=[
            Button(
                # Labelled, not a bare icon - see the docstring. SECONDARY keeps
                # it quiet rather than a blurple slab; this is a utility control
                # sitting under a footer, not the point of the panel.
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"todo_refresh:{view}|0",
                emoji=_partial("refresh") or U_REFRESH,
                label="Check now",
            ),
        ]),
    ]


def _nav_select(view: str, counts: dict, *,
                unchecked: set[str] | None = None,
                unavailable: dict[str, str] | None = None) -> ActionRow:
    """House-style navigation: a TextSelectMenu, not a row of coloured buttons.

    clan/dashboard/dashboard.py navigates with a select whose options carry an
    emoji and a description. That is strictly more informative than buttons -
    every section's status is visible without clicking - and it is why the old
    button row read as a different product from the rest of the bot.

    Deliberately NOT registered with group=. The group mechanism requires each
    option's `value` to BE a registered action name, so it cannot carry a page
    number. This is a plain action that reads ctx.interaction.values[0] itself.
    """
    unchecked = unchecked or set()
    unavailable = unavailable or {}

    def describe(key: str) -> str:
        value = counts.get(key)
        if value is None:
            return "couldn't be checked — try Check now"
        if key in unchecked:
            if value:
                noun = "account" if value == 1 else "accounts"
                verb = "has" if value == 1 else "have"
                return f"{value} {noun} {verb} hits left · some unchecked"
            return "some accounts couldn't be checked"
        if value == 0 and unavailable.get(key):
            return unavailable[key].rstrip(".")
        if value == 0:
            return "no hits left"
        noun = "account" if value == 1 else "accounts"
        verb = "has" if value == 1 else "have"
        return f"{value} {noun} {verb} hits left"

    def describe_blocked() -> str:
        value = counts.get(VIEW_PRIVATE)
        if not value:
            return "every war log is readable"
        noun = "account" if value == 1 else "accounts"
        log = "war log" if value == 1 else "war logs"
        return f"{value} {noun} with unreadable {log}"

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
            description=describe(VIEW_RAID),
            value=VIEW_RAID,
            emoji=_partial(VIEW_EMOJI[VIEW_RAID]),
            is_default=view == VIEW_RAID,
        ),
        SelectOption(
            label=VIEW_LABEL[VIEW_PRIVATE],
            description=describe_blocked(),
            value=VIEW_PRIVATE,
            emoji=U_PRIVATE,
            is_default=view == VIEW_PRIVATE,
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
    # limit == 0 means "there is nothing to count" - the Private War Logs view,
    # where the row is the account itself rather than an outstanding attack.
    lead = f"{row.used}/{row.limit}" if row.limit else ""
    return f"{lead} {th} {row.account}".replace("  ", " ").strip()


def _render_rows(rows: list, verb: str = "", stamp_of=None) -> list:
    """Rows grouped by clan, one Text Display per clan.

    THE DEADLINE IS PER CLAN, NOT PER BLOCK. It was a block heading for one
    build, which was wrong in the worst way available: two clans in the same
    Prep Day block were 9h29m and 3h51m from battle day, and the heading showed
    min() - "starts in 4 hours" - over both of them. A member reading it for the
    first clan would have turned up five and a half hours early. A single number
    covering rows it is not true for is the same defect as the empty-state bug,
    and it is worse than showing no number at all.

    It goes on its OWN SUBTEXT LINE under the clan name rather than as a suffix
    to it. A suffix has to survive the longest clan name in the family plus a
    chip on one line - "Morning Woods!" alone puts that at 28 characters, i.e.
    at the wrap limit before anything grows. A subtext line cannot collide with
    the name at all, and being smaller it reads as a caption on the clan rather
    than competing with it.

    `verb` is "" for callers with no timing (the Private War Logs view).
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

        head = f"**{first.clan_name}**"
        if verb and stamp_of is not None:
            # min() WITHIN one clan is safe - every row here belongs to the same
            # war, so the stamps are equal. It is only a lie ACROSS clans.
            stamps = [s for s in (stamp_of(r) for r in members) if s]
            if stamps:
                head += f"\n-# {verb} <t:{min(stamps)}:R>"
        body = f"{head}\n{lines}"

        # Section + Thumbnail(clan badge). The badge is the visual anchor that
        # the old "🕒 CLAN · prep · opens in 18h · closes in 2 days" header was
        # trying and failing to be - that header wrapped to two lines on a phone
        # for every single clan. The clan name still sits alone on a short line;
        # only its own deadline follows, on the line below.
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


def _split_blocks(view: str, rows: list) -> list:
    """Rows split into render blocks, in render order. THE ONE SPLITTER.

    Returns [(key, group), ...] with empty groups dropped, so len() is the
    block count the renderer will actually emit.

    It exists because the component-budget pager has to predict exactly what
    the renderers will produce. Two copies of this predicate - one to render,
    one to count - is the drift shape that produced the raid: and cwlwar: cache
    bugs. There is one, and both callers use it.
    """
    if view == VIEW_PRIVATE:
        groups = (
            ("private", [r for r in rows if r.reason != "error"]),
            ("failed", [r for r in rows if r.reason == "error"]),
        )
    else:
        groups = (
            ("live", [r for r in rows if r.state != "preparation"]),
            ("prep", [r for r in rows if r.state == "preparation"]),
        )
    return [(key, group) for key, group in groups if group]


def _clans_in(rows: list) -> list:
    """Distinct clan tags in first-seen order, with one representative row each.

    Same ordering _render_rows builds, for the same reason: clan order on the
    panel must not reshuffle between identical runs.
    """
    seen: dict = {}
    for row in rows:
        if row.clan_tag not in seen:
            seen[row.clan_tag] = row
    return list(seen.values())


def _page_cost(view: str, rows: list) -> int:
    """Components a page of `rows` will emit, INCLUDING fixed panel furniture.

    Mirrors the renderers exactly:
      Container 1 + title 1 + separator 1 + _nav_block 7          = PANEL_FIXED
      per block:  1 heading, +1 separator when it is not the first
      per clan:   3 with a Thumbnail (Section + Text + Thumbnail),
                  1 without (a bare Text), +1 separator between clans
      notes and the pagination row are RESERVED, never conditional - see the
      constants.
    """
    cost = PANEL_FIXED + RESERVE_NOTES + RESERVE_PAGINATION
    for index, (_key, group) in enumerate(_split_blocks(view, rows)):
        cost += 1                      # block heading Text
        if index:
            cost += 1                  # separator between blocks
        clans = _clans_in(group)
        for first in clans:
            cost += 3 if _thumbnail_for(first) else 1
        cost += max(0, len(clans) - 1)  # separators between clans
    return cost


def _paginate(view: str, rows: list) -> list:
    """Rows split into pages that each fit COMPONENT_BUDGET. Greedy, in order.

    PAGES ARE VARIABLE LENGTH. The old PAGE_SIZE=20 capped ROWS, which is not
    the thing that costs components - CLANS are. 20 rows in 2 clans is 19
    components; 20 rows in 20 clans is ~91, and Discord rejects the whole
    message with a 400. See docs/todo-dashboard.md.

    A page always takes at least one row even if that row alone would exceed
    the budget, or the loop would not terminate. A single clan cannot realistically
    do that - one clan with a thumbnail is PANEL_FIXED + reserves + 4 = 20 - but
    the guard is there so a future costlier row cannot hang the render.
    """
    if not rows:
        return [[]]

    pages: list = []
    current: list = []
    for row in rows:
        candidate = current + [row]
        if current and _page_cost(view, candidate) > COMPONENT_BUDGET:
            pages.append(current)
            current = [row]
        else:
            current = candidate
    if current:
        pages.append(current)
    return pages


def _timing_blocks(view: str, rows: list) -> list:
    """Rows split by STATE. Each clan states its own deadline.

    The grouping is still state-first, and that survived the per-clan-timing
    fix deliberately. What defines a block is the one thing that IS uniform
    across it - can I attack right now, or am I waiting - and that is the most
    important distinction on the panel. Regrouping by clan would interleave
    live and waiting clans and lose it. Only the CLOCK varied, so only the
    clock moved down to the clan.

    A heading may therefore state the state and nothing else. Anything a
    heading asserts has to be true of every row beneath it.
    """
    live_label, prep_label = BLOCK_LABELS.get(view, BLOCK_LABELS_DEFAULT)
    # Labels/verbs by key. The SPLIT itself comes from _split_blocks so the
    # pager's cost model and this renderer cannot disagree about block count.
    spec = {
        "live": (EMOJI_LIVE, live_label, "ends", lambda r: r.ends_at),
        "prep": (EMOJI_WAITING, prep_label, "starts", lambda r: r.starts_at),
    }

    out: list = []
    for key, group in _split_blocks(view, rows):
        emoji_name, label, verb, stamp_of = spec[key]
        if out:
            out.append(Separator(divider=True, spacing=hikari.SpacingType.SMALL))
        # "###" - one step below the panel title, one step above the clan name.
        # NO TIMESTAMP HERE. The heading carries only what is true of every row
        # under it, which is the STATE. The clock is per clan.
        heading = f"### {_emoji(emoji_name)} {label}".replace("###  ", "### ")
        out.append(Text(content=heading.rstrip()))
        out.extend(_render_rows(group, verb, stamp_of))
    return out


def _reason_blocks(rows: list) -> list:
    """Blocked accounts split by WHY the clan is unreadable.

    The two need different responses from the user - a private war log is a
    conversation with that clan's leader, a lookup failure is "try again" - so
    they must not be mixed into one list. Same block-heading and clan-grouping
    treatment as _timing_blocks; only the split differs.
    """
    # Split via _split_blocks, same as _timing_blocks, so the pager's cost
    # model predicts this renderer exactly.
    spec = {
        "private": (U_PRIVATE, "Private war logs",
                    "these clans have their war log set to private"),
        "failed": (U_FAILED, "Lookup failed",
                   "couldn't reach the API for these — try Check now"),
    }

    out: list = []
    for key, group in _split_blocks(VIEW_PRIVATE, rows):
        glyph, label, hint = spec[key]
        if out:
            out.append(Separator(divider=True, spacing=hikari.SpacingType.SMALL))
        # Same "###" step as _timing_blocks - these are block headings too.
        out.append(Text(content=f"### {glyph} {label}\n-# {hint}"))
        out.extend(_render_rows(group))
    return out


def render_dashboard(view: str, page: int, data: dict, *,
                     checked_at: int | None = None,
                     auto_refresh: bool = False,
                     refresh_until: datetime | None = None) -> list:
    """The dashboard itself.

    `data` maps view name -> ViewData. A view whose ViewData is None could not
    be computed at all.
    """
    counts = {
        k: (v.count if v is not None and v.ok else None)
        for k, v in data.items()
    }
    unchecked = {
        k for k, v in data.items()
        if v is not None and v.ok and bool(v.incomplete)
    }
    unavailable = {
        k: v.unavailable
        for k, v in data.items()
        if v is not None and v.ok and v.unavailable
    }
    current = data.get(view)

    # Title carries the count so the header line does one more job. NO trailing
    # blank line, which was dead vertical space at the top of every panel.
    #
    # "##", a step ABOVE the repo's house H3. Deliberate departure: this panel
    # has three nested levels under the title, and at H3 the title was the same
    # size as the clan names, so nothing read as the title. H1 is far too large
    # on a phone. Other panels in the repo are flat and stay at H3.
    outstanding = counts.get(view)
    glyph = _emoji(VIEW_EMOJI.get(view, "")) or VIEW_UNICODE.get(view, "")
    title = f"## {glyph} {VIEW_LABEL[view]}".replace("##  ", "## ")
    if outstanding:
        # "to do" is wrong for Private War Logs - those accounts are not work,
        # they are clans to go and ask about.
        title += f" · {outstanding}" if view == VIEW_PRIVATE else f" · {outstanding} to do"
        if view != VIEW_PRIVATE and _urgency_accent(current) == RED_ACCENT:
            title += f" {U_URGENT}"
    body: list = [Text(content=title)]

    if current is None or not current.ok:
        # RULE: could-not-read must never render as all-caught-up.
        body.append(Separator(divider=True))
        body.append(Text(content=(
            coc_maintenance.banner() if coc_maintenance.in_maintenance() else (
                "⚠️ **Couldn't read this section.**\n"
                "The Clash API or the proxy didn't answer. This is not the same as "
                "having nothing to do — press Check now in a minute."
            )
        )))
        pages = 1
        page = 0
    else:
        rows = current.rows
        # PAGED ON COMPONENTS, NOT ROWS. Pages are variable length by design -
        # a page of 2 clans may hold 20 rows, a page of 20 clans holds far
        # fewer, because clans are what cost components.
        row_pages = _paginate(view, rows)
        pages = len(row_pages)
        page = max(0, min(page, pages - 1))
        window = row_pages[page]

        body.append(Separator(divider=True))
        if not rows and getattr(current, "incomplete", ""):
            body.append(Text(content=(
                coc_maintenance.banner() if coc_maintenance.in_maintenance() else (
                    "⚠️ **Couldn't check every linked account.**\n"
                    f"-# {current.incomplete}"
                )
            )))
        elif not rows and getattr(current, "unavailable", ""):
            # The EVENT is not running. Completely different from "you have done
            # everything" - saying "all caught up" between raid weekends would
            # be claiming credit for work that was never available.
            body.append(Text(content=(
                f"**{current.unavailable}**\n"
                "-# Raid weekend runs Friday 07:00 → Monday 07:00 UTC."
            )))
        elif not rows and view == VIEW_PRIVATE:
            # An empty Private War Logs view is good news, not "nothing to do".
            body.append(Text(content=f"{U_CAUGHT_UP} **Every clan is readable.**"))
        elif not rows:
            # "All caught up" is a verdict on the WHOLE dashboard, so it may
            # only be said when every section is empty. Saying it per-view told
            # a user with three pending CWL hits that there was nothing to do,
            # because the default view happened to be the empty one.
            # VIEW_PRIVATE excluded for the same reason it cannot be the landing
            # view: it is not outstanding work, so pointing at it here would be
            # telling the user they still have things to do when they do not.
            elsewhere = [
                VIEW_LABEL[k] for k, v in data.items()
                if k != view and k != VIEW_PRIVATE and v is not None and v.ok and v.count
            ]
            if elsewhere:
                body.append(Text(content=(
                    f"**Nothing due in {VIEW_LABEL[view]}.**\n"
                    f"-# Still to do in: {', '.join(elsewhere)}"
                )))
            else:
                body.append(Text(content=f"{U_CAUGHT_UP} **All caught up.**"))
        else:
            if view == VIEW_PRIVATE:
                body.extend(_reason_blocks(window))
            else:
                body.extend(_timing_blocks(view, window))

        if current.notes:
            body.append(Separator(divider=True))
            body.append(Text(content="\n".join(f"-# {n}" for n in current.notes)))

    # Pagination goes ABOVE the red footer, with the content it pages - not
    # below it next to Refresh, where it was parked half-built. _nav_block
    # places it between the view select and the footer.
    pager = None
    if pages > 1:
        # DO NOT CLAMP THE PAGE NUMBERS IN THE custom_id. Clamping is what made
        # this row 400 the moment it first rendered:
        #
        #   page 0        : max(0, page-1) == 0 == page   -> back collides with the label
        #   last page     : min(pages-1, page+1) == page   -> next collides with the label
        #   middle pages  : page-1, page, page+1           -> fine
        #
        # so it failed on the FIRST page of every paginated payload and worked
        # in between. Discord rejects the whole message with
        #   components.0.components.16.components.1.custom_id
        #    - Component custom id cannot be duplicated
        #
        # Unclamped, the three ids are consecutive integers and cannot collide.
        # Out-of-range is already handled twice over: is_disabled stops the
        # click, and render_dashboard clamps whatever arrives
        # (page = max(0, min(page, pages - 1))), so even a hand-crafted
        # todo_war:-1 lands on page 0.
        pager = ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"todo_{view}:{page - 1}",
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
                custom_id=f"todo_{view}:{page + 1}",
                label="▶",
                is_disabled=page >= pages - 1,
            ),
        ])

    body.extend(_nav_block(
        view, counts, pager, unchecked=unchecked, unavailable=unavailable,
        checked_at=checked_at,
        auto_refresh=auto_refresh,
        refresh_until=refresh_until,
    ))

    # The footer is emitted by _nav_block, above the freshness row.
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
    todo_data.cache_put(CACHE_LOGOS, logos, TTL_LOGOS)


class _Perf:
    """One [todo-perf] line per invocation. Measurement, not theory.

    Exists because five rounds of the utcnow bug and four of the "all caught
    up" bug were all fixes shipped on a theory of where the time or the fault
    was, with nothing measuring it. The rule that came out of both: after two
    failed fixes, stop fixing and start measuring.

    WARM RUNS LIE. `warm=` reports how many player entries were already cached
    when the run started. A run with warm=46/46 is measuring the cache, not the
    API, and reading it as "the fetch is fast now" is the same mistake in a new
    place. Compare like with like.
    """

    def __init__(self) -> None:
        self._t0 = time.perf_counter()
        self._phase: dict[str, float] = {}
        # Time spent purely on measurement, subtracted from total=.
        self._excluded: float = 0.0
        self.meta: dict[str, object] = {}
        # Per-invocation, so calls= counts THIS run. The counters live in
        # todo_data because that is where the network calls are.
        todo_data.reset_calls()

    @contextlib.contextmanager
    def timing(self, name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            self._phase[name] = self._phase.get(name, 0.0) + (time.perf_counter() - start)

    @contextlib.contextmanager
    def instrumentation_only(self, name: str):
        """Time work that exists ONLY to be measured, and keep it out of total=.

        `serialize=` re-runs component.build(), which hikari is going to run
        again inside ctx.respond(). That duplicate pass is real wall clock the
        user would not otherwise pay, so it is subtracted from total= - which
        therefore keeps meaning "what the user waited for" and stays comparable
        with every number measured before this field existed.

        Safe to run twice: hikari's ContainerComponentBuilder.build() builds a
        fresh JSONObjectBuilder, reads self._components.copy(), and mutates
        nothing (hikari 2.3.5, impl/special_endpoints.py:2579-2597).
        """
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - start
            self._phase[name] = self._phase.get(name, 0.0) + elapsed
            self._excluded += elapsed

    def _ms(self, name: str) -> int:
        return int(self._phase.get(name, 0.0) * 1000)

    def _field(self, name: str) -> str:
        """A phase's value, or "-" if it was NEVER MEASURED ON THIS PATH.

        `_ms` returns 0 for a missing key, which rendered a phase nobody
        observed identically to one that genuinely took no time. The refresh
        path has no defer and cannot time the send - the dispatcher owns the
        response - so the line asserted `defer=0ms send=0ms` about work it had
        not looked at, next to a real `send=1055ms` on the command path.

        A key exists in _phase only if timing() or instrumentation_only() ran
        for it, so presence is exactly "was this observed". Any future
        path-specific phase gets this for free.
        """
        if name not in self._phase:
            return "-"
        return f"{self._ms(name)}ms"

    def line(self) -> str:
        total = time.perf_counter() - self._t0 - self._excluded
        # fetch is the sum of the two halves rather than a third timer, so the
        # parts always add up to the whole and cannot drift apart. "-" only if
        # NEITHER half was observed - a partial sum would be a lie of the same
        # kind _field exists to prevent.
        if "players" in self._phase or "views" in self._phase:
            fetch = f"{self._ms('players') + self._ms('views')}ms"
        else:
            fetch = "-"
        meta = " ".join(f"{k}={v}" for k, v in self.meta.items())

        # calls= and worst= are what tell 50 throttled calls apart from 2 slow
        # ones. A phase total alone cannot, and those two need opposite fixes.
        stats = todo_data.call_stats()
        n = int(stats.get("n", 0))
        worst_ms = int(float(stats.get("worst", 0.0)) * 1000)
        mean_ms = int(float(stats.get("total", 0.0)) * 1000 / n) if n else 0

        # by_label answers "did leaguewar run at all", which worst= could only
        # answer by luck. Sorted so the field is stable between runs and diffable
        # by eye. Always a real count, never "-": it is a counter, not a phase,
        # so {} means zero calls rather than not-measured.
        by_label = stats.get("by_label") or {}
        by_label_str = "{" + ",".join(f"{k}:{v}" for k, v in sorted(by_label.items())) + "}"

        # WHAT total= SPANS DIFFERS BY PATH, so it says which.
        #
        # Command and component paths print after their own send, so total
        # covers everything the user waited for. Any future path that does not
        # observe a send is labelled to-render and is not directly comparable.
        #
        # Derived from whether send was observed rather than set by the caller,
        # so it cannot drift out of sync with reality. The NUMBER on the command
        # path is unchanged - tonight's cold-path arc stays the baseline.
        span = "to-send" if "send" in self._phase else "to-render"

        return (
            f"[todo-perf] {meta} "
            f"defer={self._field('defer')} resolve={self._field('resolve')} "
            f"logos={self._field('logos')} fetch={fetch} "
            f"(players={self._field('players')} views={self._field('views')}) "
            # render= builds BUILDER OBJECTS only. serialize= is the JSON pass
            # hikari does inside send=, sampled here. send= is everything:
            # serialisation + bucket acquire + HTTP + deserialize_message. So
            # (send - serialize) is the round trip plus deserialisation, which
            # cannot be separated further without reaching into hikari.
            f"render={self._field('render')} serialize={self._field('serialize')} "
            f"send={self._field('send')} "
            f"calls={n} mean={mean_ms}ms worst={worst_ms}ms/{stats.get('worst_label', '-')} "
            f"by_label={by_label_str} "
            # up= is the process uptime. A warm=0 run with up= under a minute is
            # a restart, not a cache bug - the cache is in-process and dies with
            # it. Without this the two are indistinguishable from the panel.
            f"up={int(todo_data.uptime())}s cached={todo_data.cache_size()} "
            f"total={total:.2f}s({span})"
        )


def _with_account_failures(view_data: todo_data.ViewData, error_count: int) -> todo_data.ViewData:
    """Mark a partially computed view without hiding rows that did load."""
    if coc_maintenance.in_maintenance():
        # Same banner the section-level notes use, so the DEDUPE below is what
        # keeps the panel from saying it twice. In the screenshot that started
        # this, these two warnings stacked: the player fan-out failed AND the
        # war lookups failed, one break, two lines.
        warning = coc_maintenance.banner()
    else:
        warning = (
            f"{error_count} linked account(s) could not be loaded — "
            "these results may be incomplete"
        )
    notes = list(view_data.notes)
    if view_data.rows and warning not in notes:
        notes.append(warning if coc_maintenance.in_maintenance() else f"⚠️ {warning}")
    return replace(view_data, notes=notes, incomplete=warning)


async def _load(bot, coc_client, discord_id: int, force: bool = False, mongo=None,
                perf: "_Perf | None" = None, auto_refresh: bool = False,
                refresh_until: datetime | None = None,
                recheck_negative_after: float | None = None):
    """Resolve tags and compute every section.

    Returns (data, problem). `problem` is a ready-to-render component list when
    the dashboard cannot be shown at all; otherwise None.

    All sections compute together because the nav badges show every count, and
    because they share the same per-clan fetches - once a clan's war is warm,
    the marginal cost of the other sections is near zero.
    """
    perf = perf or _Perf()
    if force:
        # ONE call, and it owns the prefix list. Enumerating prefixes here is
        # what froze the freshness stamp: "raid:" was missing from this list
        # while oldest_fill read it, so raid entries - TTL of DAYS out of
        # season - survived every Refresh and pinned the clock. Only the two
        # per-invocation keys are passed in.
        todo_data.drop_render_caches((f"links:{discord_id}", CACHE_LOGOS))

    if mongo is not None:
        with perf.timing("logos"):
            await _load_clan_logos(mongo)

    cache_key = f"links:{discord_id}"
    tags = todo_data.cache_get(cache_key)
    if tags is None:
        with perf.timing("resolve"):
            tags = await resolve_tags(discord_id)
        if tags is None:
            # Lookup FAILED. Not the same as having no accounts, and the user
            # must not be sent off to fix a problem they do not have.
            return None, _notice(
                "Couldn't reach the link service",
                "The Clash↔Discord link service didn't answer, so I can't tell "
                "which accounts are yours.\n\n"
                "This is a problem on their end, not yours — try again shortly.",
                checked_at=int(time.time()), auto_refresh=auto_refresh,
                refresh_until=refresh_until,
            )
        todo_data.cache_put(cache_key, tags, todo_data.TTL_LINKS)

    if not tags:
        return None, _notice(
            "No linked accounts",
            "I couldn't find any Clash of Clans accounts linked to your Discord.\n\n"
            "Link one with ClashKing's `/link` command (you'll need your in-game "
            "API token from **Settings → More Settings → API Token**), then run "
            "`/todo` again.",
            checked_at=int(time.time()), auto_refresh=auto_refresh,
            refresh_until=refresh_until,
        )

    # Counted BEFORE the fetch, or every entry reads as a hit afterwards.
    perf.meta["tags"] = len(tags)
    warm, linked = todo_data.live_keys_for("player:", tags)
    perf.meta["warm"] = f"{warm}/{linked}"

    # ONE semaphore for the whole invocation, shared by both phases. It used to
    # live inside fetch_accounts, which bounded the player phase at 8 and left
    # the view phase at 1 - four plain for/await loops. 46 of 102 cold calls ran
    # in parallel and the other 56 ran strictly one at a time.
    sem = todo_data.new_semaphore()

    # History discovery is one bulk Mongo read, and watch enrollment is one
    # bulk write. Both run beside the already-required player API fan-out so
    # cross-clan support adds no serial lookup phase to the interaction.
    with perf.timing("players"):
        (accounts, errors), candidates, _watched = await asyncio.gather(
            todo_data.fetch_accounts(coc_client, tags, sem=sem),
            clan_history.load_candidates(mongo, tags),
            clan_history.watch_players(mongo, tags),
        )
    candidate_clans = {a.clan_tag for a in accounts if a.clan_tag}
    candidate_clans.update(
        candidate.clan_tag
        for player_candidates in candidates.values()
        for candidate in player_candidates
        if candidate.clan_tag
    )
    perf.meta["clans"] = len(candidate_clans)
    if not accounts:
        # The whole-panel version of the same story. Nothing loaded at all,
        # which during a break is the NORMAL outcome rather than the rare one -
        # "Couldn't load your accounts" points the user at their own setup for
        # a problem that is entirely Supercell's.
        if coc_maintenance.in_maintenance():
            return None, _notice(
                f"{U_MAINTENANCE} Clash is in maintenance",
                "The game's API stopped answering "
                f"<t:{int(coc_maintenance.started_at().timestamp())}:R>, so "
                "there's nothing I can check right now.\n\n"
                "Nothing is wrong with your accounts, and nothing is lost. "
                "Supercell doesn't publish an end time — press Check now again "
                "in a few minutes.",
                checked_at=int(time.time()), auto_refresh=auto_refresh,
                refresh_until=refresh_until,
            )
        return None, _notice(
            "Couldn't load your accounts",
            "Your accounts are linked, but the Clash API didn't answer for any "
            "of them. Try again shortly.",
            checked_at=int(time.time()), auto_refresh=auto_refresh,
            refresh_until=refresh_until,
        )

    # Persist the current player responses while war/CWL network work runs.
    # This does not gate the first view; it is awaited before returning so a
    # clean shutdown cannot silently discard the observation.
    history_write = asyncio.create_task(clan_history.record_presence(
        mongo, clan_history.presences_from_accounts(accounts)
    ))

    # All four view builds together: they share the per-clan fetches, so timing
    # them separately would just show the first one paying for the rest.
    # The four builders still run in SEQUENCE, deliberately. They share the
    # per-clan caches - build_blocked_view re-reads the same war: keys
    # build_war_view just filled - so running them concurrently would turn those
    # cache hits back into duplicate in-flight requests. The win is inside each
    # builder, where the clans now fan out.
    with perf.timing("views"):
        war = await todo_data.build_war_view(
            coc_client, accounts, sem=sem, candidates=candidates,
            recheck_negative_after=recheck_negative_after,
        )
        cwl = await todo_data.build_cwl_view(
            coc_client, accounts, sem=sem, candidates=candidates,
            recheck_negative_after=recheck_negative_after,
        )
        raid = await todo_data.build_raid_view(coc_client, accounts, sem=sem)
        blocked = await todo_data.build_blocked_view(
            coc_client, accounts, sem=sem, candidates=candidates,
            recheck_negative_after=recheck_negative_after,
        )

    perf.meta["war_private"] = sum(
        row.reason == "private" for row in blocked.rows
    )
    perf.meta["war_error"] = sum(
        row.reason == "error" for row in blocked.rows
    )

    if errors:
        print(f"[todo] {len(errors)} account lookups failed for {discord_id}: {errors[:5]}")
        war, cwl, raid, blocked = (
            _with_account_failures(view_data, len(errors))
            for view_data in (war, cwl, raid, blocked)
        )

    await history_write

    return {VIEW_WAR: war, VIEW_CWL: cwl, VIEW_RAID: raid, VIEW_PRIVATE: blocked}, None


# ---------------------------------------------------------------------------
# Command
# ---------------------------------------------------------------------------

async def _deliver_panel(ctx, bot, components: list):
    """Return ``(message, schedulable)`` after delivering the panel."""
    if ctx.guild_id is not None:
        # The defer already fixed this response as ephemeral. Editing it is one
        # webhook call and never exposes linked-account activity in the guild.
        message = await ctx.interaction.edit_initial_response(components=components)
        return message, False

    try:
        message = await bot.rest.create_message(ctx.channel_id, components=components)
    except Exception as exc:  # noqa: BLE001 - a visible panel matters more than route choice
        print(f"[todo] standalone DM delivery failed; using interaction response: "
              f"{type(exc).__name__}: {exc}")
        fallback = _manual_fallback_panel(components)
        message = await ctx.interaction.edit_initial_response(components=fallback)
        return message, False

    # The standalone message has no "used /todo" response treatment. Remove the
    # deferred loading placeholder only after delivery succeeds, so a failure
    # can never leave the user with no response at all.
    try:
        await ctx.interaction.delete_initial_response()
    except Exception as exc:  # noqa: BLE001 - the dashboard itself was delivered
        print(f"[todo] could not remove deferred DM placeholder: "
              f"{type(exc).__name__}: {exc}")
    return message, True


async def _activate_auto_panel(
    ctx,
    bot,
    mongo,
    message,
    components: list,
    view: str,
    *,
    kind: str = "dashboard",
    checked_at: int | None = None,
) -> bool:
    """Make this the sole automatic panel, then promote its neutral footer."""
    user_id = int(ctx.user.id)
    channel_id = int(ctx.channel_id)
    message_id = int(message.id)
    if getattr(message, "webhook_id", None):
        return False
    owner_id = todo_sessions.session_id(user_id, channel_id)
    async with _refresh_lock(owner_id):
        claimed = await _takeover_locked(
            bot, mongo,
            user_id=user_id,
            channel_id=channel_id,
            message_id=message_id,
            view=view,
            page=0,
            kind=kind,
            trigger="command",
        )
        if claimed is None:
            return False
        _generation, until = claimed
        promoted = _automatic_status_panel(
            components,
            checked_at=int(checked_at if checked_at is not None else time.time()),
            refresh_until=until,
        )
        try:
            await bot.rest.edit_message(
                channel_id, message_id, components=promoted
            )
        except Exception as exc:  # noqa: BLE001 - scheduler repairs a neutral owner
            print(f"[todo] automatic footer promotion failed "
                  f"user={user_id} message={message_id}: "
                  f"{type(exc).__name__}: {exc}")
        return True


async def _takeover_locked(
    bot,
    mongo,
    *,
    user_id: int,
    channel_id: int,
    message_id: int,
    view: str,
    page: int,
    kind: str,
    trigger: str,
) -> tuple[str, datetime] | None:
    """Demote every promised predecessor, then CAS ownership to this panel.

    Caller holds the deterministic owner lock through its candidate edit.
    A failure before the CAS leaves the old owner scheduled; a failure after it
    leaves the candidate conservatively manual until the scheduler repairs it.
    """
    owner_ok, owner = await todo_sessions.read_owner(
        mongo, user_id=user_id, channel_id=channel_id
    )
    panels_ok, panels = await todo_sessions.active_panels(
        mongo, user_id=user_id, channel_id=channel_id
    )
    if not owner_ok or not panels_ok:
        return None

    previous_ids = {
        todo_sessions.panel_message_id(panel)
        for panel in panels
        if todo_sessions.panel_message_id(panel)
        and todo_sessions.panel_message_id(panel) != message_id
    }
    for old_message_id in sorted(previous_ids):
        try:
            await bot.rest.edit_message(
                channel_id, old_message_id, components=_retired_panel()
            )
        except hikari.NotFoundError:
            # A deleted panel has no visible promise to preserve.
            pass
        except Exception as exc:  # noqa: BLE001 - do not orphan an auto promise
            print(f"[todo-sessions] replacement aborted user={user_id} "
                  f"old={old_message_id} new={message_id}; old remains active: "
                  f"{type(exc).__name__}: {exc}")
            return None
        _snapshot_drop(user_id, channel_id, old_message_id)

    # Numeric pre-owner rows are still scheduler-visible for upgrade safety.
    # Remove them before claim and require success, otherwise a demoted legacy
    # panel could repaint itself automatic after the new owner is promoted.
    cleaned = await todo_sessions.remove_legacy_rows(mongo, panels)
    if not cleaned:
        return None

    claimed = await todo_sessions.claim(
        mongo,
        user_id=user_id,
        channel_id=channel_id,
        message_id=message_id,
        view=view,
        page=page,
        kind=kind,
        trigger=trigger,
        expected_owner=owner,
    )
    if claimed is None:
        return None
    return claimed

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
        # DEFER FIRST, ALWAYS. The 3-second window is on the FIRST response to
        # an interaction, and the fetch behind this panel takes tens of seconds.
        perf = _Perf()
        is_dm = ctx.guild_id is None
        notice_refresh_until = (
            todo_sessions.new_refresh_until() if is_dm else None
        )
        with perf.timing("defer"):
            await ctx.defer(ephemeral=not is_dm)

        data, problem = await _load(
            bot, coc_client, ctx.user.id, mongo=mongo, perf=perf,
            auto_refresh=is_dm,
            refresh_until=notice_refresh_until,
        )
        if problem:
            checked_at = int(time.time())
            delivered = (
                _manual_fallback_panel(problem, checked_at=checked_at)
                if is_dm else problem
            )
            with perf.timing("send"):
                sent, schedulable = await _deliver_panel(ctx, bot, delivered)
            message_id = int(getattr(sent, "id", 0) or 0)
            _snapshot_put(
                int(ctx.user.id), int(ctx.channel_id), message_id,
                data, problem, checked_at,
            )
            perf.meta["result"] = "notice"
            print(perf.line(), flush=True)
            if schedulable:
                await _activate_auto_panel(
                    ctx, bot, mongo, sent, problem, VIEW_WAR, kind="notice",
                    checked_at=checked_at,
                )
            return
        # Open on the first view that actually has work. Always opening on War
        # meant a user whose only pending hits were CWL saw an empty War view
        # and read it as the whole dashboard's verdict.
        opening = next(
            (v for v in VIEW_OPENING_ORDER
             if data.get(v) is not None and data[v].ok and data[v].count),
            VIEW_WAR,
        )
        refresh_until = todo_sessions.new_refresh_until() if is_dm else None
        with perf.timing("render"):
            checked_at = int(time.time())
            components = render_dashboard(
                opening, 0, data, checked_at=checked_at, auto_refresh=is_dm,
                refresh_until=refresh_until,
            )
            delivered = (
                _manual_fallback_panel(components, checked_at=checked_at)
                if is_dm else components
            )
        # Sampled BEFORE the send so a slow serialisation is visible even if the
        # send then fails. Excluded from total= - see instrumentation_only.
        # Public API, not a monkey-patch: this is the same build() hikari calls
        # at impl/rest.py:1484/:1499 from _build_message_payload.
        with perf.instrumentation_only("serialize"):
            for _component in components:
                _component.build()

        with perf.timing("send"):
            sent, schedulable = await _deliver_panel(ctx, bot, delivered)

        message_id = int(getattr(sent, "id", 0) or 0)
        _snapshot_put(
            int(ctx.user.id), int(ctx.channel_id), message_id,
            data, None, checked_at,
        )

        # Printed BEFORE the todo_sessions write. The line must describe what
        # the user actually waited for, and the row is bookkeeping that happens
        # once the panel is already on screen.
        perf.meta["view"] = opening
        print(perf.line(), flush=True)

        if schedulable:
            await _activate_auto_panel(
                ctx, bot, mongo, sent, components, opening,
                checked_at=checked_at,
            )


# ---------------------------------------------------------------------------
# View handlers
#
# Every parameter that could come from stored state is defaulted, and none is
# read. The dispatcher's button_store lookup always misses for /todo - that is
# the design - so a handler must be callable with only ctx and action_id.
# ---------------------------------------------------------------------------

async def _switch(ctx, view: str, action_id: str, coc_client, bot, force: bool = False,
                  mongo=None, trigger: str = "nav", *,
                  _lock_held: bool = False) -> None:
    try:
        page = int(action_id.split("|")[-1])
    except (TypeError, ValueError):
        page = 0
    # A forced refresh is the ONLY guaranteed-cold measurement available - it
    # drops the caches first, so warm= reads 0 and the fetch numbers are real
    # API time rather than dictionary lookups. It is the sample worth trusting.
    #
    # Component handlers own their edit (no_return=True), so send= measures the
    # actual response while the same lock as the scheduler is still held.
    perf = _Perf()
    perf.meta["path"] = trigger
    is_dm = getattr(ctx, "guild_id", None) is None
    message = getattr(getattr(ctx, "interaction", None), "message", None)
    message_id = int(getattr(message, "id", 0) or 0)
    channel_id = int(getattr(ctx, "channel_id", 0) or 0)
    user_id = int(ctx.user.id)
    owner_id = (
        todo_sessions.session_id(user_id, channel_id)
        if is_dm and channel_id else None
    )

    # Queue rapid DM interactions before any network work. Locking only around
    # the final edit lets an older slow click overwrite a newer fast click.
    if owner_id is not None and not _lock_held:
        async with _refresh_lock(owner_id):
            return await _switch(
                ctx, view, action_id, coc_client, bot, force=force,
                mongo=mongo, trigger=trigger, _lock_held=True,
            )

    snapshot = None if force else _snapshot_get(
        user_id, channel_id, message_id
    )
    loaded = snapshot is None
    if snapshot is not None:
        data, problem = snapshot.data, snapshot.problem
        checked_at = snapshot.checked_at
        perf.meta["snapshot"] = "hit"
    else:
        refresh_until = (
            todo_sessions.new_refresh_until() if is_dm else None
        )
        data, problem = await _load(
            bot, coc_client, ctx.user.id, force=force, mongo=mongo, perf=perf,
            auto_refresh=is_dm,
            refresh_until=refresh_until,
        )
        checked_at = int(time.time())
        perf.meta["snapshot"] = "bypass" if force else "miss"
    kind = "notice" if problem else "dashboard"

    def publish_snapshot() -> None:
        if not loaded or not message_id or not channel_id:
            return
        _snapshot_put(
            user_id, channel_id, message_id,
            data, problem, checked_at,
        )

    def render(*, automatic: bool, until: datetime | None) -> list:
        with perf.timing("render"):
            if problem:
                if automatic and until is not None:
                    return _automatic_status_panel(
                        problem, checked_at=checked_at, refresh_until=until
                    )
                return _manual_fallback_panel(problem, checked_at=checked_at)
            dashboard = render_dashboard(
                view, page, data,
                checked_at=checked_at,
                auto_refresh=automatic,
                refresh_until=until,
            )
            if is_dm and not automatic:
                return _manual_fallback_panel(
                    dashboard, checked_at=checked_at
                )
            return dashboard

    if not is_dm:
        rendered = problem if problem else render(automatic=False, until=None)
        with perf.timing("send"):
            await ctx.respond(components=rendered, edit=True)
        publish_snapshot()
        print(perf.line(), flush=True)
        return

    if not message_id or not channel_id or getattr(message, "webhook_id", None):
        rendered = render(automatic=False, until=None)
        with perf.timing("send"):
            await ctx.respond(components=rendered, edit=True)
        publish_snapshot()
        print(perf.line(), flush=True)
        return

    # The recursive entry above acquired this before _load(), and retains it
    # through ctx.respond(). nullcontext keeps direct unit calls defensive.
    lock_context = (
        contextlib.nullcontext()
        if _lock_held else _refresh_lock(str(owner_id))
    )
    async with lock_context:
        automatic = False
        exact_until = None
        if force:
            claimed = await _takeover_locked(
                bot, mongo,
                user_id=user_id,
                channel_id=channel_id,
                message_id=message_id,
                view=view,
                page=page,
                kind=kind,
                trigger=trigger,
            )
            if claimed is not None:
                _generation, exact_until = claimed
                automatic = True
        else:
            owner_ok, owner = await todo_sessions.read_owner(
                mongo,
                user_id=user_id,
                channel_id=channel_id,
                include_expired=False,
            )
            if (
                owner_ok
                and owner is not None
                and todo_sessions.panel_message_id(owner) == message_id
                and owner.get("generation")
            ):
                updated = await todo_sessions.update_navigation(
                    mongo,
                    owner_id=owner_id,
                    message_id=message_id,
                    generation=str(owner["generation"]),
                    view=view,
                    page=page,
                    kind=kind,
                    trigger=trigger,
                    checked_at=(
                        datetime.fromtimestamp(checked_at, tz=timezone.utc)
                        if loaded else None
                    ),
                )
                if updated:
                    exact_until = owner.get("refresh_until")
                    automatic = isinstance(exact_until, datetime)

        rendered = render(automatic=automatic, until=exact_until)
        # no_return=True keeps the generic dispatcher from editing a second
        # time after this owner lock is released.
        with perf.timing("send"):
            await ctx.respond(components=rendered, edit=True)
        publish_snapshot()
    print(perf.line(), flush=True)


@register_action("todo_war", no_return=True)
@lightbulb.di.with_di
async def todo_war(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    await _switch(ctx, VIEW_WAR, action_id, coc_client, bot, mongo=mongo, trigger="view:war")


@register_action("todo_cwl", no_return=True)
@lightbulb.di.with_di
async def todo_cwl(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    await _switch(ctx, VIEW_CWL, action_id, coc_client, bot, mongo=mongo, trigger="view:cwl")


@register_action("todo_raid", no_return=True)
@lightbulb.di.with_di
async def todo_raid(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    await _switch(ctx, VIEW_RAID, action_id, coc_client, bot, mongo=mongo, trigger="view:raid")


@register_action("todo_private", no_return=True)
@lightbulb.di.with_di
async def todo_private(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    await _switch(
        ctx, VIEW_PRIVATE, action_id, coc_client, bot,
        mongo=mongo, trigger="view:private",
    )


@register_action("todo_nav", no_return=True)
@lightbulb.di.with_di
async def todo_nav(
        ctx: lightbulb.components.MenuContext,
        action_id: str = VIEW_WAR,
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    """The select-menu router.

    Registered WITHOUT group=, so the dispatcher does not try to resolve the
    selected value as an action name - it reads values[0] here instead. That is
    what lets an option carry "refresh" as well as a view name.
    """
    values = getattr(ctx.interaction, "values", None) or []
    choice = values[0] if values else action_id
    # Refresh moved out of the select and became a button, but panels already
    # sitting in DM history still carry a select with a "refresh" option and
    # will keep firing this forever. Same reasoning as an action alias: the old
    # value must go on working, because you cannot reach back and edit those
    # messages.
    if choice == "refresh":
        await _switch(ctx, action_id or VIEW_WAR, "0", coc_client, bot, force=True, mongo=mongo, trigger="nav:refresh")
        return
    if choice not in VIEW_ORDER:
        choice = VIEW_WAR
    await _switch(ctx, choice, "0", coc_client, bot, mongo=mongo, trigger="nav:select")


@register_action("todo_refresh", no_return=True)
@lightbulb.di.with_di
async def todo_refresh(
        ctx: lightbulb.components.MenuContext,
        action_id: str = "war|0",
        coc_client: coc.Client = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
        **kwargs,
) -> None:
    view = action_id.split("|")[0] if action_id else VIEW_WAR
    if view not in VIEW_ORDER:
        view = VIEW_WAR
    await _switch(ctx, view, action_id, coc_client, bot, force=True, mongo=mongo, trigger="refresh")


# ---------------------------------------------------------------------------
# DM automatic refresh
# ---------------------------------------------------------------------------

async def _refresh_session(
    session: dict,
    bot,
    coc_client,
    mongo,
    *,
    recheck_negative_after: float | None = None,
) -> str:
    """Refresh one stored DM panel and return a cycle-accounting outcome."""
    document_id = session.get("_id")
    legacy = isinstance(document_id, int) and not session.get("generation")
    message_id = todo_sessions.panel_message_id(session)
    generation = None if legacy else str(session.get("generation", "") or "")
    channel_id = int(session.get("channel_id", 0) or 0)
    user_id = int(session.get("user_id", 0) or 0)
    expected_owner_id = (
        todo_sessions.session_id(user_id, channel_id)
        if user_id and channel_id else ""
    )
    owner_id = expected_owner_id if legacy else str(document_id or "")
    valid_legacy = bool(
        legacy and int(document_id) == message_id
    )
    valid_current = bool(generation and owner_id == expected_owner_id)
    if (
        not owner_id or not message_id or not channel_id or not user_id
        or (legacy and not valid_legacy)
        or (not legacy and not valid_current)
    ):
        _snapshot_drop(user_id, channel_id, message_id)
        await todo_sessions.discard(mongo, document_id)
        return "removed"

    async def legacy_owner_outcome() -> str | None:
        """Stop a leftover legacy job once a deterministic owner exists."""
        owner_ok, current_owner = await todo_sessions.read_owner(
            mongo,
            user_id=user_id,
            channel_id=channel_id,
            include_expired=False,
        )
        if not owner_ok:
            await todo_sessions.postpone(
                mongo, owner_id, message_id, generation
            )
            return "failed"
        if current_owner is None:
            return None
        removed = await todo_sessions.discard(mongo, document_id)
        if removed:
            return "removed"
        await todo_sessions.postpone(
            mongo, owner_id, message_id, generation
        )
        return "failed"

    if legacy:
        # Avoid the Clash load entirely for a leftover row when cleanup after a
        # takeover previously failed. Recheck under the lock after the load too.
        async with _refresh_lock(owner_id):
            outcome = await legacy_owner_outcome()
        if outcome is not None:
            return outcome

    try:
        # Network data may load concurrently; ownership and the actual Discord
        # edit may not. A replacement during this load changes generation, so
        # the exact read under the lock skips this stale result.
        perf = _Perf()
        perf.meta["path"] = "automatic"
        data, problem = await _load(
            bot, coc_client, user_id, mongo=mongo, perf=perf,
            auto_refresh=True,
            refresh_until=session.get("refresh_until"),
            recheck_negative_after=recheck_negative_after,
        )

        async with _refresh_lock(owner_id):
            if legacy:
                # Cleanup after takeover is best-effort. If it failed (or the
                # process stopped between claim and cleanup), never let the old
                # numeric row repaint a retired panel as automatic.
                outcome = await legacy_owner_outcome()
                if outcome is not None:
                    return outcome

            read_ok, latest = await todo_sessions.get(
                mongo, owner_id, message_id, generation
            )
            if not read_ok:
                await todo_sessions.postpone(
                    mongo, owner_id, message_id, generation
                )
                return "failed"
            if latest is None:
                return "skipped"
            view = latest.get("view", VIEW_WAR)
            if view not in VIEW_ORDER:
                view = VIEW_WAR
            try:
                page = int(latest.get("page", 0))
            except (TypeError, ValueError):
                page = 0

            checked_at = datetime.now(timezone.utc)
            rendered = problem if problem else render_dashboard(
                view, page, data,
                checked_at=int(checked_at.timestamp()), auto_refresh=True,
                refresh_until=latest.get("refresh_until"),
            )
            await bot.rest.edit_message(
                channel_id, message_id, components=rendered
            )
            _snapshot_put(
                user_id,
                channel_id,
                message_id,
                data,
                problem,
                int(checked_at.timestamp()),
            )
            recorded = await todo_sessions.mark_refreshed(
                mongo, owner_id, message_id, generation,
                checked_at=checked_at,
                kind="notice" if problem else "dashboard",
            )
            if recorded:
                return "updated"
            await todo_sessions.postpone(
                mongo, owner_id, message_id, generation,
                observed_at=checked_at,
            )
            return "failed"
    except (hikari.NotFoundError, hikari.ForbiddenError):
        _snapshot_drop(user_id, channel_id, message_id)
        removed = await todo_sessions.remove(
            mongo, owner_id, message_id, generation
        )
        if removed:
            return "removed"
        await todo_sessions.postpone(mongo, owner_id, message_id, generation)
        return "failed"
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 - retry on the next interval
        await todo_sessions.postpone(
            mongo, owner_id, message_id, generation
        )
        print(f"[todo-refresh] message {message_id} failed: "
              f"{type(exc).__name__}: {exc}")
        return "failed"


async def run_auto_refresh_cycle(bot, coc_client, mongo) -> dict[str, int]:
    """Refresh every due DM panel once, with a single shared concurrency cap."""
    _snapshot_prune()
    # A shared ten-minute freshness boundary prevents staggered panels from
    # turning the one-minute scheduler poll into one negative API recheck per
    # minute for popular clans.
    negative_cutoff = time.time() - todo_sessions.REFRESH_INTERVAL_SECONDS
    sessions = await todo_sessions.due(mongo)
    counts = {"panels": len(sessions), "updated": 0, "removed": 0,
              "failed": 0, "skipped": 0}
    if not sessions:
        return counts

    sem = asyncio.Semaphore(todo_sessions.REFRESH_CONCURRENCY)

    async def bounded(session):
        async with sem:
            return await _refresh_session(
                session, bot, coc_client, mongo,
                recheck_negative_after=negative_cutoff,
            )

    outcomes = await asyncio.gather(*(bounded(session) for session in sessions))
    for outcome in outcomes:
        counts[outcome] = counts.get(outcome, 0) + 1
    print("[todo-refresh] cycle " + " ".join(
        f"{name}={value}" for name, value in counts.items()
    ), flush=True)
    return counts


async def _auto_refresh_loop(bot, coc_client, mongo) -> None:
    while True:
        try:
            await run_auto_refresh_cycle(bot, coc_client, mongo)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 - the next poll must still run
            print(f"[todo-refresh] cycle failed: {type(exc).__name__}: {exc}")
        await asyncio.sleep(todo_sessions.REFRESH_POLL_SECONDS)


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def start_auto_refresh(
        _: hikari.StartedEvent,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
        coc_client: coc.Client = lightbulb.di.INJECTED,
        mongo: MongoClient = lightbulb.di.INJECTED,
) -> None:
    global _auto_refresh_task
    if not todo_sessions.AUTO_REFRESH_ENABLED:
        print("[todo-refresh] disabled")
        return
    if _auto_refresh_task and not _auto_refresh_task.done():
        print("[todo-refresh] task already running; start skipped")
        return
    _auto_refresh_task = asyncio.create_task(
        _auto_refresh_loop(bot, coc_client, mongo), name="todo-auto-refresh"
    )
    print("[todo-refresh] started")


@loader.listener(hikari.StoppingEvent)
async def stop_auto_refresh(_: hikari.StoppingEvent) -> None:
    global _auto_refresh_task
    if _auto_refresh_task and not _auto_refresh_task.done():
        _auto_refresh_task.cancel()
        try:
            await _auto_refresh_task
        except asyncio.CancelledError:
            pass
    _auto_refresh_task = None
    _refresh_locks.clear()
    print("[todo-refresh] stopped")
