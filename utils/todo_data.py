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

import time
from dataclasses import dataclass, field

import coc

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

# ---------------------------------------------------------------------------
# TEMPORARY DIAGNOSTICS - remove once /todo is verified.
# Every line is prefixed [todo-diag] so it greps cleanly and strips cleanly.
# ---------------------------------------------------------------------------
DIAG = True


def _d(msg: str) -> None:
    if DIAG:
        print(f"[todo-diag] {msg}", flush=True)


_cache: dict[str, tuple[float, object]] = {}

TTL_LINKS = 6 * 60 * 60      # linking is a rare manual act
TTL_WAR_ACTIVE = 120         # a hit can land any second; matches upstream max-age
TTL_WAR_IDLE = 15 * 60       # notInWar / warEnded - stable for hours
TTL_CWL_ABSENT = 60 * 60     # not in CWL - stable for WEEKS outside the season
TTL_CWL_ACTIVE = 600         # rounds advance once per day


def cache_get(key: str):
    """Cached value, or None if absent or expired."""
    hit = _cache.get(key)
    if hit is None:
        if key.startswith("cwl:"):
            _d(f"cache MISS {key}")
        return None
    expires_at, value = hit
    if time.monotonic() >= expires_at:
        _cache.pop(key, None)
        if key.startswith("cwl:"):
            _d(f"cache EXPIRED {key}")
        return None
    if key.startswith("cwl:"):
        _d(f"cache HIT {key} -> {value!r}")
    return value


def cache_put(key: str, value, ttl: int) -> None:
    _cache[key] = (time.monotonic() + ttl, value)


def cache_drop_prefix(prefix: str) -> int:
    """Drop every key with this prefix. Used by Refresh. Returns count dropped."""
    doomed = [k for k in _cache if k.startswith(prefix)]
    for k in doomed:
        _cache.pop(k, None)
    return len(doomed)


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


@dataclass(frozen=True, slots=True)
class ViewData:
    """One section of the dashboard.

    ok=False means WE COULD NOT READ THIS. It must never render as "all caught
    up" - see rule 2 at the top of this module.
    """
    rows: list[Row] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    ok: bool = True

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

async def fetch_accounts(coc_client: coc.Client, tags: list[str]) -> tuple[list[Account], list[str]]:
    """Resolve tags to accounts. Returns (accounts, errors).

    One call per tag - Supercell has no bulk player endpoint, and coc.py's
    get_players iterator only parallelises, it does not batch. Sequential here
    is deliberate: coc.py's throttler enforces ~33ms spacing anyway (the
    effective key count is 1, not the 10 main.py asks for - login_with_tokens
    overwrites it), so fanning out buys little and costs clarity.
    """
    accounts: list[Account] = []
    errors: list[str] = []

    for tag in tags:
        cached = cache_get(f"player:{tag}")
        if cached is not None:
            accounts.append(cached)
            continue
        try:
            player = await coc_client.get_player(tag)
        except coc.NotFound:
            # A linked tag for an account that no longer exists. Common with
            # abandoned alts; not worth surfacing to the user.
            continue
        except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as exc:
            errors.append(f"{tag}: {type(exc).__name__}")
            continue
        except Exception as exc:  # noqa: BLE001 - never let one tag kill the dashboard
            errors.append(f"{tag}: {type(exc).__name__}")
            continue

        clan = getattr(player, "clan", None)
        badge = getattr(getattr(clan, "badge", None), "medium", None) if clan else None
        account = Account(
            tag=player.tag,
            name=player.name,
            clan_tag=clan.tag if clan else None,
            clan_name=clan.name if clan else None,
            town_hall=getattr(player, "town_hall", 0) or 0,
            clan_badge=badge,
        )
        cache_put(f"player:{tag}", account, TTL_WAR_ACTIVE)
        accounts.append(account)

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
    _d(f"_get_cwl_round ENTER clan={clan_tag!r} client={type(coc_client).__name__}")
    key = f"cwl:{clan_tag}"
    cached = cache_get(key)
    if cached is not None:
        _d(f"_get_cwl_round RETURN cached for {clan_tag}")
        return cached

    try:
        _d(f"_get_cwl_round calling get_league_group({clan_tag!r}) NOW")
        group = await coc_client.get_league_group(clan_tag)
        _d(f"_get_cwl_round get_league_group returned {type(group).__name__} "
           f"state={getattr(group, 'state', '<no state>')!r}")
    except coc.NotFound:
        _d(f"_get_cwl_round EARLY-RETURN none: NotFound for {clan_tag}")
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
        _d(f"_get_cwl_round EARLY-RETURN none: group state "
           f"{getattr(group, 'state', '<None group>')!r} for {clan_tag}")
        result = ("none", None)
        cache_put(key, result, TTL_CWL_ABSENT)
        return result

    rounds = getattr(group, "rounds", None) or []
    _d(f"_get_cwl_round {clan_tag} rounds={len(rounds)}")
    if not rounds:
        _d(f"_get_cwl_round EARLY-RETURN none: no rounds for {clan_tag}")
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

    _d(f"_get_cwl_round {clan_tag} candidates={candidates}")
    if not candidates:
        _d(f"_get_cwl_round EARLY-RETURN none: no non-#0 war tags for {clan_tag}")
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
        notes.append(f"{private} account(s) in clans with private war logs — can't check")
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

    _d(f"build_cwl_view ENTER accounts={len(accounts)}")
    by_clan: dict[str, list[Account]] = {}
    for acct in accounts:
        if acct.clan_tag:
            by_clan.setdefault(acct.clan_tag, []).append(acct)
    _d(f"build_cwl_view clans={list(by_clan.keys())}")

    for clan_tag, members in by_clan.items():
        kind, war = await _get_cwl_round(coc_client, clan_tag)
        _d(f"build_cwl_view {clan_tag} -> kind={kind} "
           f"state={getattr(war, 'state', None)!r}")

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
