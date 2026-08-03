"""Data layer for /todo - what each linked account still owes.

Read docs/todo-dashboard-proposal.md for the design and
docs/clashking-war-endpoints.md for the payload shapes this is written against.

THREE RULES THIS MODULE EXISTS TO ENFORCE:

1. ONLY ACTIONABLE ROWS. An account with nothing to do is not a row. That is
   what makes this a to-do list rather than a report.

2. "COULD NOT READ" IS NEVER "NOTHING TO DO". A section that failed to load must
   say so. An empty section and an unreadable one look identical to a user and
   mean opposite things - the reference implementation became untrustworthy
   exactly here. Every ViewData carries `ok` for this reason.

3. NON-ACTIONABLE BUT RELEVANT IS STILL SHOWN. Preparation-phase wars ARE rows
   - you cannot attack yet, but you owe the attack and the deadline is set.
   Private war logs cannot be read at all, so they surface as a note. Silently
   omitting either hides accounts the user needs to know about.

4. NEVER str() A coc.py STATE ENUM. See _state() below. This one mistake
   emptied both views while every fetch underneath them succeeded.

NEVER call coc.Client.get_current_war() here. It silently makes 2-10 calls -
regular war, then league group, then it PROBES the last round, then fetches the
chosen round - so calling it per clan triples the budget invisibly. This module
calls get_clan_war and get_league_group explicitly so the fan-out is visible.
"""

import asyncio
import time
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass, field

import coc

# ---------------------------------------------------------------------------
# TEMPORARY DIAGNOSTICS for the raid view - remove once verified on a live
# raid weekend. Every line is prefixed [todo-diag] so it greps and strips
# cleanly. The war/CWL diagnostics were removed after those views were proven.
# ---------------------------------------------------------------------------
DIAG = True


def _d(msg: str) -> None:
    if DIAG:
        print(f"[todo-diag] {msg}", flush=True)

# ---------------------------------------------------------------------------
# Cache
#
# In-process only. Nothing here needs to survive a restart: a cold cache costs
# one dashboard open, and the bot restarts routinely (Restart=always, plus
# reboot.py's os._exit(0)). coc.py's own FIFO cache already absorbs the
# positive path - measured TTLs from the proxy are 60s on players, ~95-120s on
# currentwar, 600s on clans - so this layer exists mainly for the NEGATIVE
# answers, which coc.py cannot cache because they are derived, not URL-keyed.
#
# On a normal day most sections are "nothing to do", and that answer is stable
# for days. Caching it is where the real saving is.
# ---------------------------------------------------------------------------

# (monotonic expiry, unix fill time, value). The fill time exists so the panel
# can say how old the DATA is rather than when it was rendered.
_cache: dict[str, tuple[float, float, object]] = {}

TTL_LINKS = 6 * 60 * 60      # linking is a rare manual act
TTL_WAR_ACTIVE = 120         # a hit can land any second; matches upstream max-age

# The player cache is THE PLAYER->CLAN MAPPING, and that is why it gets its own
# constant instead of borrowing TTL_WAR_ACTIVE as it used to. Staleness here has
# a specific, user-visible failure: a member who moved clans is shown a war for
# the clan they left. Keep it short. Anyone raising TTL_WAR_ACTIVE for war
# reasons must not silently drag clan membership along with it.
#
# "player:" is in DATA_PREFIXES, so Refresh already drops this - which is the
# escape hatch for exactly the clan-change case, and the thing that was missing
# for "raid:" when the freshness stamp froze.
TTL_PLAYER = 120

# Simultaneous player lookups. coc.py's own BasicThrottler is the real ceiling -
# it spaces request STARTS ~33ms apart across the whole client (throttle_limit
# defaults to 30/s) and releases its lock before the request runs, so ~30/s is
# the floor no matter what this is set to. This bounds open sockets rather than
# request rate, and it is deliberately modest: proxy.clashk.ing is ClashKing's
# infrastructure, offered free, and 46 simultaneous lookups is not neighbourly.
FETCH_CONCURRENCY = 8
TTL_WAR_IDLE = 15 * 60       # notInWar / warEnded - stable for hours
TTL_CWL_ABSENT = 60 * 60     # not in CWL - stable for WEEKS outside the season
TTL_CWL_ACTIVE = 600         # rounds advance once per day


def cache_get(key: str):
    """Cached value, or None if absent or expired."""
    hit = _cache.get(key)
    if hit is None:
        return None
    expires_at, _filled_at, value = hit
    if time.monotonic() >= expires_at:
        _cache.pop(key, None)
        return None
    return value


def cache_put(key: str, value, ttl: int) -> None:
    """Store a value with its expiry AND the wall-clock time it was fetched.

    `filled_at` is unix epoch, not monotonic, because it is rendered as
    <t:N:R>. Expiry stays monotonic so a clock change cannot break eviction.
    """
    _cache[key] = (time.monotonic() + ttl, time.time(), value)


# THE PREFIXES THAT MAKE UP ONE /todo RENDER. Deliberately ONE tuple, shared by
# the Refresh drop and the freshness stamp.
#
# It is one tuple because it used to be two, and they diverged: the drop listed
# player/war/cwl and the stamp read player/war/cwl/RAID. Raid entries therefore
# survived every Refresh, and out of season their TTL is _seconds_until_raid_opens()
# - DAYS. oldest_fill() takes the min, so the stamp was pinned to whenever the
# process first rendered a raid view and never moved again, on any view. Refresh
# refetched everything correctly; only the clock was frozen. See docs/todo-dashboard.md.
#
# Add a new cached data prefix HERE and both sides get it. Do not re-inline a
# prefix list at a call site.
DATA_PREFIXES: tuple[str, ...] = ("player:", "war:", "cwl:", "raid:")

# Wall-clock of the last drop_render_caches(). Sole purpose is the consistency
# check in oldest_fill: after a drop, no live entry can predate it.
_last_drop_at: float = 0.0


def oldest_fill(prefixes: tuple[str, ...] = DATA_PREFIXES) -> float | None:
    """When the OLDEST still-live cache entry under these prefixes was fetched.

    This is what "updated N minutes ago" must be built from. Using render time
    would be a lie precisely when it matters: a panel served entirely from cache
    renders now but shows data from minutes ago, and the cached case is exactly
    when the user needs to know how stale it is.

    Oldest rather than newest, because the panel is only as fresh as its
    stalest component.

    THE INVARIANT: after drop_render_caches(), everything live under these
    prefixes was necessarily filled after the drop, so this moves. If it does
    not, some prefix is being read but not dropped - which is the exact bug this
    function once had, and it is invisible from the panel: the button works, the
    data is fresh, the clock just lies. So it is checked, and the check NAMES
    the surviving keys rather than reporting that something is wrong.
    """
    now = time.monotonic()
    live = [
        (filled_at, key)
        for key, (expires_at, filled_at, _value) in _cache.items()
        if expires_at > now and key.startswith(prefixes)
    ]
    if not live:
        return None

    result = min(f for f, _k in live)
    # 1s of slack: the drop and the refills inside one request are the same
    # instant for this purpose, and float comparison should not manufacture a
    # warning out of that.
    if _last_drop_at and result < _last_drop_at - 1:
        survivors = sorted(k for f, k in live if f < _last_drop_at - 1)
        print(
            f"[todo-diag] STALE STAMP: oldest_fill={result:.0f} predates last drop "
            f"{_last_drop_at:.0f}. Read-but-not-dropped keys: {survivors[:8]}"
        )
    return result


def live_keys(prefix: str) -> int:
    """How many unexpired entries sit under this prefix.

    For instrumentation: a run whose players were already cached is not
    measuring the same thing as a cold one, and comparing the two without
    knowing which is which is how you conclude the wrong thing about where the
    time goes.
    """
    now = time.monotonic()
    return sum(
        1 for key, (expires_at, _f, _v) in _cache.items()
        if expires_at > now and key.startswith(prefix)
    )


def cache_drop_prefix(prefix: str) -> int:
    """Drop every key with this prefix. Returns count dropped.

    Prefer drop_render_caches() for the Refresh path - it owns the full list.
    This stays public for the one-off prefixes (a user's links, the logo map)
    that are not part of DATA_PREFIXES.
    """
    doomed = [k for k in _cache if k.startswith(prefix)]
    for k in doomed:
        _cache.pop(k, None)
    return len(doomed)


def drop_render_caches(extra: tuple[str, ...] = ()) -> int:
    """Everything behind one /todo render. THE Refresh entry point.

    `extra` carries the per-invocation prefixes that cannot be constants - the
    caller's own links key, the clan logo map.
    """
    global _last_drop_at
    _last_drop_at = time.time()
    dropped = 0
    for prefix in DATA_PREFIXES + tuple(extra):
        dropped += cache_drop_prefix(prefix)
    _d(f"drop_render_caches dropped={dropped} prefixes={DATA_PREFIXES + tuple(extra)}")
    return dropped


# ---------------------------------------------------------------------------
# Shapes
# ---------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Row:
    """One actionable account. Rendered as a single line."""
    account: str
    tag: str
    clan_name: str
    clan_tag: str
    used: int
    limit: int
    ends_at: int | None   # unix seconds, for <t:N:R>. None if unknown.
    # "inWar" or "preparation". A preparation row is REAL WORK - you cannot
    # attack yet, but you owe the attack and the deadline is already fixed.
    # Dropping these is what made the dashboard say "all caught up" while three
    # accounts had pending CWL hits.
    state: str = "inWar"
    starts_at: int | None = None
    town_hall: int = 0
    clan_badge: str | None = None
    # Why this row exists, when it is not an outstanding attack. "private" =
    # the clan's war log is closed; "error" = we could not reach the API. Those
    # need different responses - one is a conversation with a clan leader, the
    # other is "try again" - so they are grouped separately in the view.
    reason: str = ""


@dataclass(frozen=True, slots=True)
class ViewData:
    """One section of the dashboard.

    ok=False means WE COULD NOT READ THIS. It must never render as "all caught
    up" - see rule 2 at the top of this module.
    """
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ok: bool = True
    # Set when the view has nothing to show because the EVENT is not running,
    # as opposed to the user having finished everything. "No raid weekend right
    # now" and "you have used all your attacks" are opposite meanings and must
    # never render the same way.
    unavailable: str = ""

    @property
    def count(self) -> int:
        return len(self.rows)


@dataclass(frozen=True, slots=True)
class Account:
    """A resolved linked account and where it currently sits."""
    tag: str
    name: str
    clan_tag: str | None
    clan_name: str | None
    town_hall: int = 0
    clan_badge: str | None = None   # badge URL, for the per-clan Thumbnail


# ---------------------------------------------------------------------------
# Fetching
# ---------------------------------------------------------------------------

async def _fetch_one_player(coc_client: coc.Client, tag: str, sem: asyncio.Semaphore):
    """One player lookup. NEVER RAISES - returns (tag, Account|None, error|None).

    Swallowing here rather than at the gather is deliberate. asyncio.gather with
    return_exceptions=True would hand back a mixed list of results and exception
    objects, and one malformed tag would then need type-checking at every use.
    A function that cannot raise keeps the caller a plain loop.

    BaseException - CancelledError above all - is deliberately NOT caught. A
    cancelled request must stay cancelled, or shutdown hangs.
    """
    async with sem:
        try:
            player = await coc_client.get_player(tag)
        except coc.NotFound:
            # A linked tag for an account that no longer exists. Common with
            # abandoned alts; not an error worth surfacing to the user.
            return tag, None, None
        except Exception as exc:  # noqa: BLE001 - never let one tag kill the dashboard
            return tag, None, f"{tag}: {type(exc).__name__}"

    clan = getattr(player, "clan", None)
    badge = getattr(getattr(clan, "badge", None), "medium", None) if clan else None
    return tag, Account(
        tag=player.tag,
        name=player.name,
        clan_tag=clan.tag if clan else None,
        clan_name=clan.name if clan else None,
        town_hall=getattr(player, "town_hall", 0) or 0,
        clan_badge=badge,
    ), None


async def fetch_accounts(
    coc_client: coc.Client,
    tags: list[str],
    concurrency: int = FETCH_CONCURRENCY,
) -> tuple[list[Account], list[str]]:
    """Resolve tags to accounts, CONCURRENTLY. Returns (accounts, errors).

    One call per tag - Supercell has no bulk player endpoint. This was
    sequential, on the reasoning that coc.py's throttler enforces ~33ms spacing
    so fanning out would buy little. That reasoning was wrong, and measurement
    is what showed it: BasicThrottler acquires its lock, computes the gap,
    sleeps, and RELEASES THE LOCK BEFORE THE REQUEST RUNS
    (coc/http.py, BasicThrottler.__aenter__). So it spaces request STARTS ~33ms
    apart and never waits for completion.

    Sequential therefore cost 46 x (33ms + round-trip). Concurrent costs
    46 x 33ms, because the throttler becomes the floor instead of the round
    trip stacking on top of it. The per-request latency stops accumulating.

    ORDER IS PRESERVED. Results come back in completion order; the returned
    list is rebuilt in `tags` order, because account order decides the order
    clans appear on the panel and a dashboard that reshuffles itself between
    identical runs is a bug report waiting to happen.
    """
    errors: list[str] = []
    resolved: dict[str, Account] = {}

    # Cache pass first, so the semaphore only ever gates real network calls.
    misses: list[str] = []
    for tag in tags:
        cached = cache_get(f"player:{tag}")
        if cached is not None:
            resolved[tag] = cached
        else:
            misses.append(tag)

    if misses:
        sem = asyncio.Semaphore(max(1, concurrency))
        results = await asyncio.gather(
            *(_fetch_one_player(coc_client, tag, sem) for tag in misses)
        )
        for tag, account, error in results:
            if error:
                errors.append(error)
            if account is not None:
                resolved[tag] = account
                cache_put(f"player:{tag}", account, TTL_PLAYER)

    accounts: list[Account] = [resolved[tag] for tag in tags if tag in resolved]

    return accounts, errors


async def _get_war(coc_client: coc.Client, clan_tag: str):
    """Regular war for a clan.

    Returns (kind, war):
        ("war", ClanWar)   a live or ended regular war
        ("private", None)  war log is private - we cannot know
        ("none", None)     definitively not in a regular war
        ("error", None)    lookup failed; the answer is unknown

    Exception ladder copied from fwa_points_monitor.py:79-92, which is the only
    correctly-layered Clash error handling in the repo.
    """
    key = f"war:{clan_tag}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    try:
        war = await coc_client.get_clan_war(clan_tag)
    except coc.PrivateWarLog:
        result = ("private", None)
        cache_put(key, result, TTL_WAR_IDLE)
        return result
    except coc.NotFound:
        result = ("none", None)
        cache_put(key, result, TTL_WAR_IDLE)
        return result
    except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as exc:
        print(f"[todo] war lookup failed for {clan_tag}: {type(exc).__name__}")
        return ("error", None)
    except Exception as exc:  # noqa: BLE001
        print(f"[todo] war lookup errored for {clan_tag}: {type(exc).__name__}: {exc}")
        return ("error", None)

    if war is None:
        result = ("none", None)
        cache_put(key, result, TTL_WAR_IDLE)
        return result

    result = ("war", war)
    # WarState defines __eq__ without __hash__, so its members are unhashable -
    # `state in {…}` raises TypeError. Tuples compare fine, and ExtendedEnum
    # equality accepts plain strings.
    active = _state(war) in ("inWar", "preparation")
    cache_put(key, result, TTL_WAR_ACTIVE if active else TTL_WAR_IDLE)
    return result


async def _get_cwl_round(coc_client: coc.Client, clan_tag: str):
    """The clan's war in the current CWL round.

    Returns (kind, war):
        ("war", ClanWar)   our war in the active round
        ("none", None)     definitively not in CWL
        ("error", None)    could not read CWL - MUST NOT render as "nothing to do"

    "Not in CWL" has TWO distinct responses and both are normal:
      - HTTP 404          -> coc.NotFound
      - HTTP 200 with state "notInWar" and rounds []
    Gate on the API, never on the calendar. June 2026 ran a bonus CWL, so
    "days 1-9 of the month" is not a reliable window.
    """
    key = f"cwl:{clan_tag}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    try:
        group = await coc_client.get_league_group(clan_tag)
    except coc.NotFound:
        result = ("none", None)
        cache_put(key, result, TTL_CWL_ABSENT)
        return result
    except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as exc:
        # GatewayError is expected here: coc.py documents an upstream bug where
        # requesting the league group of a clan searching for a CWL match times
        # out. Still an unknown answer, so still an error.
        print(f"[todo] CWL group lookup failed for {clan_tag}: {type(exc).__name__}")
        return ("error", None)
    except Exception as exc:  # noqa: BLE001
        print(f"[todo] CWL group lookup errored for {clan_tag}: {type(exc).__name__}: {exc}")
        return ("error", None)

    if group is None or _state(group) in ("notInWar", "groupNotFound", "ended"):
        result = ("none", None)
        cache_put(key, result, TTL_CWL_ABSENT)
        return result

    rounds = getattr(group, "rounds", None) or []
    if not rounds:
        result = ("none", None)
        cache_put(key, result, TTL_CWL_ABSENT)
        return result

    # coc.py filters "#0" placeholder war tags out of rounds when building the
    # model, so the last remaining round is the newest one that has been drawn.
    #
    # Check the PREVIOUS round too. During a round transition the newest round
    # is in `preparation` while the previous one is still `inWar` with attacks
    # owed - and the attacks owed are what this dashboard is for. ClashKingBot
    # handles the same case via get_current_war(cwl_round=current_preparation)
    # (classes/bot.py:664); this is the cheaper equivalent, costing one extra
    # round scan only during the transition window.
    candidates: list[str] = []
    for round_tags in (rounds[-1], rounds[-2] if len(rounds) > 1 else []):
        for war_tag in round_tags:
            if war_tag and war_tag != "#0" and war_tag not in candidates:
                candidates.append(war_tag)

    if not candidates:
        result = ("none", None)
        cache_put(key, result, TTL_CWL_ABSENT)
        return result

    # Prefer an inWar round over a preparation one; remember the fallback.
    fallback = None

    for war_tag in candidates:
        war_key = f"cwlwar:{war_tag}"
        war = cache_get(war_key)
        if war is None:
            try:
                war = await coc_client.get_league_war(war_tag)
            except (coc.NotFound, coc.PrivateWarLog):
                continue
            except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as exc:
                print(f"[todo] CWL war {war_tag} failed: {type(exc).__name__}")
                return ("error", None)
            except Exception as exc:  # noqa: BLE001
                print(f"[todo] CWL war {war_tag} errored: {type(exc).__name__}: {exc}")
                return ("error", None)
            if war is None:
                continue
            # A finished CWL war is immutable - cache it hard. War tags are
            # globally unique, so two family clans in one group share this entry.
            ended = _state(war) == "warEnded"
            cache_put(war_key, war, 24 * 60 * 60 if ended else TTL_CWL_ACTIVE)

        ours = getattr(war, "clan", None)
        theirs = getattr(war, "opponent", None)
        if not ((ours is not None and ours.tag == clan_tag)
                or (theirs is not None and theirs.tag == clan_tag)):
            continue

        if _state(war) == "inWar":
            result = ("war", war)
            cache_put(key, result, TTL_CWL_ACTIVE)
            return result
        if fallback is None:
            fallback = war

    if fallback is not None:
        # Our war exists but is not inWar (preparation, or already ended).
        # Hand it back and let the view decide - it filters on state.
        result = ("war", fallback)
        cache_put(key, result, TTL_CWL_ACTIVE)
        return result

    # The group said we are in CWL but no war in either round names this clan.
    # That is not "nothing to do" - it is a shape we did not expect. Say so.
    print(f"[todo] CWL group for {clan_tag} listed rounds but no war matched the clan")
    return ("error", None)


def _state(obj) -> str:
    """The API state string for a war or a league group.

    NEVER CALL str() ON A coc.py STATE. `ExtendedEnum.__str__` returns
    `in_game_name` - the human display name - not the API value:

        str(WarState.preparation)  ->  "Preparation"     NOT "preparation"
        str(WarState.in_war)       ->  "In War"          NOT "inWar"
        str(WarState.war_ended)    ->  "War Ended"       NOT "warEnded"

    So `str(war.state) == "preparation"` is ALWAYS FALSE. That single mistake
    emptied both the war and CWL views: the wars were fetched correctly, the
    state was correct, and every row was then skipped by a comparison that
    could never be true. It cost three shipped "fixes" that each addressed a
    real but secondary bug.

    `__eq__` does accept strings (it compares against both `.name` and
    `.value`), so `war.state == "preparation"` works. `.value` is used here
    because it is unambiguous and works for the league group too, whose
    `state` is a plain str rather than an enum.
    """
    raw = getattr(obj, "state", None)
    if raw is None:
        return ""
    return str(getattr(raw, "value", raw))


def _side_for(war, clan_tag: str):
    """The WarClan object for our clan, whichever side of the war it is on."""
    ours = getattr(war, "clan", None)
    if ours is not None and ours.tag == clan_tag:
        return ours
    theirs = getattr(war, "opponent", None)
    if theirs is not None and theirs.tag == clan_tag:
        return theirs
    return None


def _used_attacks(war, player_tag: str) -> int:
    """How many attacks this player has used in this war.

    There is no "attacks used" attribute - it is len(member.attacks). And a
    member who has attacked zero times HAS NO `attacks` KEY AT ALL in the
    payload (verified: 840 war-member records in a real CWL season, 836 with an
    attacks array). coc.py normalises that to an empty list, so len() is safe -
    but never index the raw dict.
    """
    member = None
    try:
        member = war.get_member(player_tag)
    except Exception:  # noqa: BLE001 - defensive; get_member should not raise
        return 0
    if member is None:
        return 0
    return len(getattr(member, "attacks", None) or [])


def _ends_at(war) -> int | None:
    end = getattr(war, "end_time", None)
    inner = getattr(end, "time", None)
    if inner is None:
        return None
    try:
        return int(inner.timestamp())
    except Exception:  # noqa: BLE001
        return None


def _starts_at(war) -> int | None:
    start = getattr(war, "start_time", None)
    inner = getattr(start, "time", None)
    if inner is None:
        return None
    try:
        return int(inner.timestamp())
    except Exception:  # noqa: BLE001
        return None


async def build_war_view(coc_client: coc.Client, accounts: list[Account]) -> ViewData:
    """Regular-war hits still owed."""
    rows: list[Row] = []
    notes: list[str] = []
    private = 0
    unreadable = 0

    by_clan: dict[str, list[Account]] = {}
    for acct in accounts:
        if acct.clan_tag:
            by_clan.setdefault(acct.clan_tag, []).append(acct)

    for clan_tag, members in by_clan.items():
        kind, war = await _get_war(coc_client, clan_tag)

        if kind == "private":
            private += len(members)
            continue
        if kind == "error":
            unreadable += len(members)
            continue
        if kind == "none" or war is None:
            continue

        state = _state(war)
        # preparation counts. You cannot attack yet, but the attack is owed and
        # the deadline is already set - "you have a war starting" is exactly the
        # thing a to-do list should tell you.
        if state not in ("inWar", "preparation"):
            continue

        limit = getattr(war, "attacks_per_member", None) or 2
        ends = _ends_at(war)
        starts = _starts_at(war)
        for acct in members:
            if _side_for(war, clan_tag) is None:
                continue
            used = _used_attacks(war, acct.tag)
            if used >= limit:
                continue
            rows.append(Row(
                account=acct.name, tag=acct.tag,
                clan_name=acct.clan_name or clan_tag, clan_tag=clan_tag,
                used=used, limit=limit, ends_at=ends,
                state=state, starts_at=starts,
                town_hall=acct.town_hall, clan_badge=acct.clan_badge,
            ))

    # No "in war prep" note any more - preparation wars are ROWS now, not a
    # footnote. Counting them into a note is what hid them.
    if private:
        notes.append(f"🔒 {private} account(s) in clans with private war logs")
    if unreadable:
        notes.append(f"⚠️ {unreadable} account(s) could not be checked — war lookup failed")

    # ok=False only when we learned nothing at all. A partial read still shows
    # what it found, with the note above explaining the gap.
    return ViewData(rows=rows, notes=notes, ok=not (unreadable and not rows))


async def build_cwl_view(coc_client: coc.Client, accounts: list[Account]) -> ViewData:
    """CWL hits still owed in the current round."""
    rows: list[Row] = []
    notes: list[str] = []
    unreadable = 0

    by_clan: dict[str, list[Account]] = {}
    for acct in accounts:
        if acct.clan_tag:
            by_clan.setdefault(acct.clan_tag, []).append(acct)

    for clan_tag, members in by_clan.items():
        kind, war = await _get_cwl_round(coc_client, clan_tag)

        if kind == "error":
            unreadable += len(members)
            continue
        if kind == "none" or war is None:
            continue

        state = _state(war)
        # THIS LINE USED TO READ `if state != "inWar": continue` AND IT WAS THE
        # BUG. A CWL round sits in `preparation` for a full day before battle
        # day, and the group state is `preparation` for the whole first round.
        # Skipping it meant three accounts with pending CWL hits rendered as
        # "All caught up" - the worst failure this feature can have. Verified
        # live 2026-08-03 against war #8R82229L9.
        if state not in ("inWar", "preparation"):
            continue

        # CWL war payloads omit attacksPerMember entirely (verified against a
        # real season: zero occurrences in 358KB, and again on the live prep
        # war). coc.py hardcodes 1 for CWL, which is why this renders (0/1).
        limit = getattr(war, "attacks_per_member", None) or 1
        ends = _ends_at(war)
        starts = _starts_at(war)
        for acct in members:
            used = _used_attacks(war, acct.tag)
            if used >= limit:
                continue
            rows.append(Row(
                account=acct.name, tag=acct.tag,
                clan_name=acct.clan_name or clan_tag, clan_tag=clan_tag,
                used=used, limit=limit, ends_at=ends,
                state=state, starts_at=starts,
                town_hall=acct.town_hall, clan_badge=acct.clan_badge,
            ))

    if unreadable:
        notes.append(f"⚠️ {unreadable} account(s) could not be checked — CWL lookup failed")

    return ViewData(rows=rows, notes=notes, ok=not (unreadable and not rows))


async def build_blocked_view(coc_client: coc.Client, accounts: list[Account]) -> ViewData:
    """Accounts sitting in clans whose war state we cannot read.

    This exists because "17 account(s) in clans with private war logs" told the
    user a number and nothing else. The number is not the useful part - knowing
    WHICH accounts, in WHICH clans, is, because the fix is a conversation with
    those clan leaders.

    Nearly free to compute: _get_war is cached, so every lookup here is a cache
    hit from the war view that ran moments earlier.

    Rows carry no attack count - there is nothing to count - so `limit` is 0,
    which _row_line reads as "omit the count".
    """
    rows: list[Row] = []

    by_clan: dict[str, list[Account]] = {}
    for acct in accounts:
        if acct.clan_tag:
            by_clan.setdefault(acct.clan_tag, []).append(acct)

    for clan_tag, members in by_clan.items():
        kind, _war = await _get_war(coc_client, clan_tag)
        if kind not in ("private", "error"):
            continue
        for acct in members:
            rows.append(Row(
                account=acct.name, tag=acct.tag,
                clan_name=acct.clan_name or clan_tag, clan_tag=clan_tag,
                used=0, limit=0, ends_at=None,
                town_hall=acct.town_hall, clan_badge=acct.clan_badge,
                reason="private" if kind == "private" else "error",
            ))

    # Always ok=True: an empty list here is a real answer meaning "every clan is
    # readable", which is good news rather than a failure to report.
    return ViewData(rows=rows, notes=[], ok=True)


# ---------------------------------------------------------------------------
# Raid weekend
# ---------------------------------------------------------------------------

TTL_RAID_ACTIVE = 300        # attacks trickle in over ~3 days; 5 min lag is invisible


def _seconds_until_raid_opens() -> int:
    """Seconds until the next raid weekend opens (Friday 07:00 UTC).

    Used as a negative-cache TTL: outside the weekend the answer is "no raid"
    and stays that way until Friday, so there is no reason to ask again. Gated
    on the clock ONLY for the cache duration - never for the answer itself,
    which always comes from the API's own `state`.
    """
    now = datetime.now(timezone.utc)
    days_ahead = (4 - now.weekday()) % 7          # Monday=0 ... Friday=4
    opens = (now + timedelta(days=days_ahead)).replace(
        hour=7, minute=0, second=0, microsecond=0)
    if opens <= now:
        opens += timedelta(days=7)
    return max(60, int((opens - now).total_seconds()))


async def _get_raid(coc_client: coc.Client, clan_tag: str):
    """The clan's CURRENT raid weekend entry.

    Returns (kind, entry):
        ("raid", RaidLogEntry)  a raid weekend is running
        ("none", None)          no raid weekend right now
        ("error", None)         could not read - NOT the same as "none"

    Private war logs do NOT block the raid log: clans returning 403 on
    /currentwar returned 200 with full member data on /capitalraidseasons.
    """
    key = f"raid:{clan_tag}"
    cached = cache_get(key)
    if cached is not None:
        return cached

    try:
        log = await coc_client.get_raid_log(clan_tag, limit=1)
    except (coc.NotFound, coc.PrivateWarLog):
        result = ("none", None)
        cache_put(key, result, _seconds_until_raid_opens())
        return result
    except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as exc:
        print(f"[todo] raid log failed for {clan_tag}: {type(exc).__name__}")
        return ("error", None)
    except Exception as exc:  # noqa: BLE001
        print(f"[todo] raid log errored for {clan_tag}: {type(exc).__name__}: {exc}")
        return ("error", None)

    entry = None
    try:
        entry = log[0] if log and len(log) else None
    except (TypeError, IndexError):
        entry = None

    # Gate on the API's own state, never on the calendar. Midweek this endpoint
    # still returns 200 with the PREVIOUS weekend's entry, state "ended" - and
    # rendering that would tell every member they owe six attacks.
    if entry is None or str(getattr(entry, "state", "")) != "ongoing":
        result = ("none", None)
        cache_put(key, result, _seconds_until_raid_opens())
        return result

    result = ("raid", entry)
    cache_put(key, result, TTL_RAID_ACTIVE)
    return result


async def build_raid_view(coc_client: coc.Client, accounts: list[Account]) -> ViewData:
    """Capital raid attacks still owed.

    ⚠️ THE ONE THING THAT MAKES THIS VIEW WORK, AND THE EASIEST TO GET WRONG:

    The raid entry's `members` array contains ONLY players who have already
    attacked. Verified live: a 42-member clan mid-weekend returned 14 member
    entries and ZERO with attacks == 0. So the people this view exists to show
    are STRUCTURALLY ABSENT from the response, and entry.get_member(tag)
    returns None for exactly them.

    The roster must therefore be diffed against the member list, and ABSENCE
    read as zero attacks used. ClashKingBot does the same thing
    (commands/player/utils.py get_raid_hits) - it is not a workaround, it is
    the only correct reading of this endpoint.

    This is also the only view that needs a get_clan call: war and CWL take the
    clan tag from the player payload, but the roster is only on the clan.
    """
    rows: list[Row] = []
    notes: list[str] = []
    unreadable = 0
    any_ongoing = False

    by_clan: dict[str, list[Account]] = {}
    for acct in accounts:
        if acct.clan_tag:
            by_clan.setdefault(acct.clan_tag, []).append(acct)

    for clan_tag, members in by_clan.items():
        kind, entry = await _get_raid(coc_client, clan_tag)
        _d(f"build_raid_view {clan_tag} -> kind={kind} "
           f"state={getattr(entry, 'state', None)!r}")

        if kind == "error":
            unreadable += len(members)
            continue
        if kind == "none" or entry is None:
            continue

        any_ongoing = True
        ends = None
        end_time = getattr(entry, "end_time", None)
        inner = getattr(end_time, "time", None)
        if inner is not None:
            try:
                ends = int(inner.timestamp())
            except Exception:  # noqa: BLE001
                ends = None

        for acct in members:
            member = None
            try:
                member = entry.get_member(acct.tag)
            except Exception:  # noqa: BLE001
                member = None

            if member is None:
                # ABSENT means zero attacks used, not "not participating".
                # The default limit is 5; a bonus attack is EARNED during the
                # weekend, so someone who has not started cannot have one yet.
                used, limit = 0, 5
            else:
                used = getattr(member, "attack_count", 0) or 0
                base = getattr(member, "attack_limit", 0) or 0
                bonus = getattr(member, "bonus_attack_limit", 0) or 0
                # Computed FRESH every render. bonus_attack_limit is earned
                # mid-weekend, so a row can legitimately read 5/5 done, vanish,
                # then return as 5/6. ClashKingBot hardcodes /5 and misses that.
                limit = (base + bonus) or 5

            if used >= limit:
                continue

            rows.append(Row(
                account=acct.name, tag=acct.tag,
                clan_name=acct.clan_name or clan_tag, clan_tag=clan_tag,
                used=used, limit=limit, ends_at=ends,
                town_hall=acct.town_hall, clan_badge=acct.clan_badge,
            ))

    if unreadable:
        notes.append(f"⚠️ {unreadable} account(s) could not be checked — raid lookup failed")

    _d(f"build_raid_view rows={len(rows)} any_ongoing={any_ongoing} unreadable={unreadable}")

    # No clan has a running raid AND nothing failed => the weekend is simply not
    # on. That is a different message from "you have used all your attacks".
    unavailable = ""
    if not any_ongoing and not unreadable:
        unavailable = "No raid weekend right now."

    return ViewData(rows=rows, notes=notes, ok=not (unreadable and not rows),
                    unavailable=unavailable)
