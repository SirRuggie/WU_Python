"""Is the Clash API in a maintenance break right now?

Read docs/coc-maintenance-detection.md before changing anything here. The one
fact that governs this whole module:

    THERE IS NO MAINTENANCE FLAG IN THE API OR IN coc.py.

No status endpoint, no `inMaintenance` boolean, no client property. The only
signal that exists anywhere is that a request raised `coc.Maintenance`, which
is coc.py's name for HTTP 503 (coc/errors.py:139, raised at coc/http.py:382).
coc.py's own maintenance poller does exactly what this module does: fire a
request, catch the exception.

So this is an OBSERVATION LOG, not a status check. Nothing here polls. The
commands are the probe: every `except coc.Maintenance` in the codebase calls
`note_maintenance()`, every successful call calls `note_success()`. During
normal operation that costs zero extra requests, and by the time a panel
renders, the flag is already right because the fetches that built the panel
are what set it.

TWO THINGS THIS DELIBERATELY DOES NOT DO
----------------------------------------
1. It never claims an END TIME. The API does not provide one - no Retry-After
   is read, no end timestamp is exposed anywhere in coc.py. Any "back in ~20
   minutes" the bot showed would be invented. `started_at()` is offered
   because elapsed time is real; there is no `ends_at()` because it is not.

2. It does not distinguish Supercell from the proxy. We talk to
   proxy.clashk.ing (utils/startup.py:78), so a 503 means "Clash is down OR
   ClashKing's proxy is" and the exception cannot tell them apart. The user
   facing copy says "Clash is in maintenance" because that is what it is the
   large majority of the time and it is what members understand - accepted
   deliberately, not overlooked.
"""

from datetime import datetime, timezone

# When the CURRENT maintenance window was first observed. None = API believed
# healthy. This is first-503-seen, not the true start: maintenance that began
# while nobody ran a command is only noticed when someone does.
_since: datetime | None = None

# When the most recent 503 was observed. Exists only for the clearing rule
# below - it is not the same as _since and must not be rendered.
_last_seen: datetime | None = None

# How recent a 503 has to be for a success to be ignored rather than treated
# as recovery.
#
# THIS CONSTANT IS THE WHOLE CORRECTNESS ARGUMENT, so it gets the explanation.
# A single /todo run makes ~50 calls, and during a live maintenance window some
# of them SUCCEED - coc.py serves them from its own FIFO response cache, filled
# before the break started (coc/http.py:299-320). Clearing the flag on any
# success would let one stale cache hit wipe a window that fifty live 503s just
# established, and which of those lands last is arbitrary.
#
# So a success only counts as recovery if no 503 has been seen for this long.
# During a break, live 503s keep arriving and keep the window alive. After
# recovery no 503s arrive at all, the last one ages past the grace, and the
# next successful call clears it. 90s is comfortably longer than one /todo run
# and comfortably shorter than any real break.
CLEAR_GRACE_SECONDS = 90


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def note_maintenance() -> None:
    """Record that a call just raised `coc.Maintenance`.

    Call this from a dedicated `except coc.Maintenance:` branch that sits
    ABOVE any `except coc.HTTPException` - Maintenance subclasses
    HTTPException, so a broader clause listed first swallows it and this is
    never reached. That ordering is the entire detection mechanism.
    """
    global _since, _last_seen
    now = _now()
    _last_seen = now
    if _since is None:
        _since = now
        print(f"[maintenance] Clash API returned 503 - entering maintenance state", flush=True)


def note_success() -> None:
    """Record that a call came back normally.

    Clears the maintenance state only once the last 503 is older than
    CLEAR_GRACE_SECONDS - see the comment on that constant for why a bare
    "any success clears it" is wrong.
    """
    global _since, _last_seen
    if _since is None:
        return
    if _last_seen is not None and (_now() - _last_seen).total_seconds() < CLEAR_GRACE_SECONDS:
        return
    duration = int((_now() - _since).total_seconds())
    print(f"[maintenance] Clash API answering again after ~{duration}s", flush=True)
    _since = None
    _last_seen = None


def in_maintenance() -> bool:
    """Whether the last thing we observed was the API refusing to answer."""
    return _since is not None


def started_at() -> datetime | None:
    """When this window was first OBSERVED, or None if the API is healthy.

    Not when maintenance actually began - see `_since`.
    """
    return _since


def reset() -> None:
    """Drop all state. For tests; nothing in the bot should call this."""
    global _since, _last_seen
    _since = None
    _last_seen = None


def banner(prefix: str = "🔧") -> str:
    """The one line that replaces every per-section failure warning.

    Rendered as a Discord relative timestamp rather than a baked-in number of
    minutes, because /todo panels persist and auto-refresh: a literal "12
    minutes ago" would be a lie an hour later, and <t:N:R> keeps counting on
    its own.

    Returns a bare "no elapsed time" variant if called while healthy, so a
    caller that checks `in_maintenance()` late cannot produce "started
    <t:None:R>".
    """
    line = f"{prefix} **Clash is in maintenance.**"
    if _since is None:
        return f"{line} Some data couldn't be loaded — nothing is wrong with your accounts."
    return (
        f"{line} The game's API stopped answering <t:{int(_since.timestamp())}:R>, "
        "so some of this may be missing or out of date. Nothing is wrong with "
        "your accounts — try again in a few minutes."
    )
