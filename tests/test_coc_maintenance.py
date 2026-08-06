"""Regression tests for maintenance detection and the message it produces.

The bug these exist to prevent is not a crash - it is /todo telling members
"36 linked account(s) could not be loaded" during a Supercell maintenance
break, which reads as "your accounts are broken" when the game is simply down.

Read docs/coc-maintenance-detection.md. The single fact the whole feature turns
on: `coc.Maintenance` SUBCLASSES `coc.HTTPException`, so an `except` clause
listing the parent first silently swallows it. That is exactly what the code
did before, and test_maintenance_is_not_shadowed_by_httpexception is the guard.
"""

import asyncio
from datetime import datetime, timedelta, timezone

import coc
import pytest

from extensions.commands import todo
from utils import coc_maintenance, todo_data


@pytest.fixture(autouse=True)
def _clean_state():
    """Module-level flag, so every test starts and finishes from healthy."""
    coc_maintenance.reset()
    todo_data._cache.clear()
    yield
    coc_maintenance.reset()
    todo_data._cache.clear()


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _text(payload) -> str:
    return "\n".join(
        str(node.get("content", ""))
        for node in _walk(payload)
        if "content" in node
    )


# ---------------------------------------------------------------------------
# The exception itself
# ---------------------------------------------------------------------------

def test_maintenance_is_not_shadowed_by_httpexception():
    """THE regression. If this ever fails, the feature is silently dead.

    `except (coc.Maintenance, coc.GatewayError, coc.HTTPException)` - the shape
    that shipped for months - collapses to `except coc.HTTPException`, because
    Python takes the first clause whose type matches and Maintenance IS an
    HTTPException. The dedicated clause has to come FIRST.
    """
    assert issubclass(coc.Maintenance, coc.HTTPException)

    order_wrong = []
    try:
        raise coc.Maintenance(503, {"reason": "inMaintenance"})
    except (coc.Maintenance, coc.GatewayError, coc.HTTPException):
        order_wrong.append("collapsed")
    assert order_wrong == ["collapsed"], "a single tuple cannot distinguish them"

    order_right = []
    try:
        raise coc.Maintenance(503, {"reason": "inMaintenance"})
    except coc.Maintenance:
        order_right.append("maintenance")
    except coc.HTTPException:
        order_right.append("generic")
    assert order_right == ["maintenance"]


def test_reason_is_empty_when_the_503_body_is_html():
    """Why the code branches on TYPE and never on `exc.reason`.

    coc/http.py:385 calls `re.sub(repl, string)` with the arguments swapped, so
    an HTML-bodied 503 always yields "". Upstream bug in 3.10.0; this test
    documents the consequence rather than asserting it is correct.
    """
    exc = coc.Maintenance(503, "")
    assert exc.reason == ""
    assert coc.Maintenance(503, {"reason": "inMaintenance"}).reason == "inMaintenance"


# ---------------------------------------------------------------------------
# The flag
# ---------------------------------------------------------------------------

def test_flag_sets_and_clears():
    assert not coc_maintenance.in_maintenance()
    coc_maintenance.note_maintenance()
    assert coc_maintenance.in_maintenance()
    assert coc_maintenance.started_at() is not None

    # Aged past the grace, so the next success counts as recovery.
    coc_maintenance._last_seen = datetime.now(tz=timezone.utc) - timedelta(
        seconds=coc_maintenance.CLEAR_GRACE_SECONDS + 5
    )
    coc_maintenance.note_success()
    assert not coc_maintenance.in_maintenance()
    assert coc_maintenance.started_at() is None


def test_a_cached_success_mid_break_does_not_clear_the_flag():
    """The reason CLEAR_GRACE_SECONDS exists.

    During a live break some calls still succeed - coc.py serves them from its
    own FIFO response cache, filled before the break started. Clearing on any
    success would let one stale hit wipe a window fifty live 503s established,
    and ordering within a /todo run is arbitrary.
    """
    coc_maintenance.note_maintenance()
    coc_maintenance.note_success()          # cache hit, moments later
    assert coc_maintenance.in_maintenance()


def test_start_time_is_the_first_503_not_the_latest():
    coc_maintenance.note_maintenance()
    first = coc_maintenance.started_at()
    coc_maintenance.note_maintenance()
    coc_maintenance.note_maintenance()
    assert coc_maintenance.started_at() == first


def test_banner_carries_a_relative_timestamp_never_an_eta():
    coc_maintenance.note_maintenance()
    banner = coc_maintenance.banner()

    assert "Clash is in maintenance" in banner
    # Relative Discord stamp, so a panel that persists keeps counting.
    assert f"<t:{int(coc_maintenance.started_at().timestamp())}:R>" in banner
    # The API gives us no end time. Anything resembling one is invented.
    for invented in ("back at", "ends at", "should be back in", "ETA"):
        assert invented.lower() not in banner.lower()


def test_banner_is_safe_to_call_while_healthy():
    """No `<t:None:R>` if a caller checks the flag late."""
    assert "None" not in coc_maintenance.banner()


# ---------------------------------------------------------------------------
# Detection at the call sites
# ---------------------------------------------------------------------------

class _MaintenanceClient:
    """A coc.Client stand-in where every endpoint is in maintenance."""

    async def get_player(self, tag):
        raise coc.Maintenance(503, {"reason": "inMaintenance"})

    async def get_clan_war(self, tag):
        raise coc.Maintenance(503, {"reason": "inMaintenance"})

    async def get_league_group(self, tag):
        raise coc.Maintenance(503, {"reason": "inMaintenance"})

    async def get_raid_log(self, tag, limit=1):
        raise coc.Maintenance(503, {"reason": "inMaintenance"})


def test_player_fetch_records_maintenance():
    client = _MaintenanceClient()
    sem = asyncio.Semaphore(1)

    tag, account, error = asyncio.run(
        todo_data._fetch_one_player(client, "#ABC", sem)
    )

    assert account is None
    assert error is not None
    assert coc_maintenance.in_maintenance()


def test_war_fetch_records_maintenance():
    client = _MaintenanceClient()
    state, war = asyncio.run(todo_data._get_war(client, "#CLAN"))

    assert (state, war) == ("error", None)
    assert coc_maintenance.in_maintenance()


def test_raid_fetch_records_maintenance():
    client = _MaintenanceClient()
    state, entry = asyncio.run(todo_data._get_raid(client, "#CLAN"))

    assert (state, entry) == ("error", None)
    assert coc_maintenance.in_maintenance()


def test_a_plain_http_error_is_not_maintenance():
    """A 500 or a rate limit must not raise the maintenance banner."""

    class _Broken(_MaintenanceClient):
        async def get_clan_war(self, tag):
            raise coc.HTTPException(500, {"reason": "serverError"})

    state, war = asyncio.run(todo_data._get_war(_Broken(), "#CLAN"))

    assert (state, war) == ("error", None)
    assert not coc_maintenance.in_maintenance()


# ---------------------------------------------------------------------------
# What the user actually sees
# ---------------------------------------------------------------------------

def test_gap_note_swaps_to_the_banner_during_maintenance():
    assert "could not be checked" in todo_data._gap_note(4, "war")

    coc_maintenance.note_maintenance()
    assert "Clash is in maintenance" in todo_data._gap_note(4, "war")
    assert "could not be checked" not in todo_data._gap_note(4, "war")


def test_unreadable_section_says_maintenance_not_couldnt_read():
    coc_maintenance.note_maintenance()
    data = {view: todo_data.ViewData() for view in todo.VIEW_ORDER}
    data[todo.VIEW_WAR] = todo_data.ViewData(ok=False)

    text = _text([c.build() for c in todo.render_dashboard(todo.VIEW_WAR, 0, data)])

    assert "Clash is in maintenance" in text
    assert "Couldn't read this section" not in text
    # Rule 2 of todo_data still holds: never "all caught up" on unread data.
    assert "All caught up" not in text


def test_the_screenshot_case_collapses_to_one_line():
    """Two stacked warnings - the player fan-out AND the war lookups - become
    one banner, not two identical ones."""
    coc_maintenance.note_maintenance()
    view = todo_data.ViewData(
        rows=[todo_data.Row(
            account="Someone", tag="#P1", clan_name="Clan", clan_tag="#C1",
            used=0, limit=2, ends_at=None,
        )],
        notes=[coc_maintenance.banner()],
    )

    merged = todo._with_account_failures(view, 36)

    assert merged.notes.count(coc_maintenance.banner()) == 1
    assert not any("could not be loaded" in note for note in merged.notes)


def test_healthy_path_keeps_the_original_counts():
    """No maintenance means the old, specific wording is untouched."""
    view = todo_data.ViewData(
        rows=[todo_data.Row(
            account="Someone", tag="#P1", clan_name="Clan", clan_tag="#C1",
            used=0, limit=2, ends_at=None,
        )],
    )

    merged = todo._with_account_failures(view, 36)

    assert any("36 linked account(s) could not be loaded" in n for n in merged.notes)
    assert not any("maintenance" in n.lower() for n in merged.notes)


# ---------------------------------------------------------------------------
# Proxy diagnostics
# ---------------------------------------------------------------------------

def test_http_detail_records_the_status_the_proxy_returned():
    """The instrumentation that answers "did the proxy rewrite the 503?".

    If proxy.clashk.ing turns Supercell's 503 into a 500 or 502, coc.py raises
    HTTPException/GatewayError instead of Maintenance and the maintenance path
    never fires - silently. This log line is what makes the next window
    self-diagnosing instead of costing a second one.
    """
    detail = todo_data._http_detail(coc.HTTPException(502, {"reason": "badGateway"}))

    assert "HTTPException" in detail
    assert "status=502" in detail
    assert "reason=badGateway" in detail


def test_http_detail_survives_a_non_http_exception():
    """`status`/`reason` are HTTPException attributes, not universal ones, and
    the clauses this feeds can be reached by other exception types."""
    detail = todo_data._http_detail(ValueError("boom"))

    assert detail == "ValueError"
