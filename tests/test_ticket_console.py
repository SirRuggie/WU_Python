import asyncio
import copy
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import hikari
import pytest

from extensions import components as dispatcher
from extensions.commands.tickets import console, resolve


def _walk(value):
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            yield from _walk(child)


def _nodes(view):
    return list(_walk([component.build() for component in view]))


def _component_nodes(view):
    return [node for node in _nodes(view) if "type" in node]


def _ticket(number=1, **overrides):
    document = {
        "_id": f"ticket_{1000 + number}",
        "type": "ticket",
        "ticket_type": "fwa" if number % 2 else "main",
        "ticket_number": number,
        "guild_id": 123456789012345678,
        "user_id": 223456789012345678 + number,
        "username": f"Applicant {number}",
        "player_tags": [f"#TAG{number}"],
        "location": {
            "id": 323456789012345678 + number,
            "staff_space_id": 423456789012345678 + number,
        },
        "status": "open",
        "created_at": datetime(2026, 8, 20, 2, number, tzinfo=timezone.utc),
    }
    document.update(overrides)
    return document


class _ContextRecoveryCursor:
    def __init__(self, documents):
        self.documents = list(documents)

    def sort(self, spec, direction=None):
        if isinstance(spec, str):
            fields = [(spec, direction or 1)]
        else:
            fields = list(spec)
        for field, order in reversed(fields):
            self.documents.sort(
                key=lambda item: (item.get(field) is None, item.get(field)),
                reverse=order < 0,
            )
        return self

    def limit(self, amount):
        self.documents = self.documents[:amount]
        return self

    async def to_list(self, length=None):
        return list(self.documents if length is None else self.documents[:length])


class _ContextRecoveryStates:
    def __init__(self, documents):
        self.documents = {item["_id"]: copy.deepcopy(item) for item in documents}
        self.query = None

    async def create_index(self, *_args, **kwargs):
        return kwargs.get("name")

    @staticmethod
    def _eligible(document):
        if document.get("kind") != "ticket_staff_context":
            return False
        lease = document.get("lease_until")
        lease_expired = isinstance(lease, datetime) and lease <= console.utcnow()
        lease_available = lease is None or lease_expired
        pending = (
            document.get("delivery_state") in {"pending", "failed"}
            or lease_expired
            or (
                "delivery_state" not in document
                and bool(document.get("delivery_error"))
            )
            or (
                "delivery_state" not in document
                and "checked_at" not in document
            )
        )
        return pending and lease_available

    def find(self, query):
        self.query = copy.deepcopy(query)
        return _ContextRecoveryCursor(
            copy.deepcopy(item)
            for item in self.documents.values()
            if self._eligible(item)
        )

    async def find_one(self, query):
        document = self.documents.get(query.get("_id"))
        return copy.deepcopy(document) if document else None

    @staticmethod
    def _matches_value(actual, expected):
        if not isinstance(expected, dict):
            return actual == expected
        if "$in" in expected:
            return actual in expected["$in"]
        return True

    async def update_one(self, query, update, **kwargs):
        document = self.documents.get(query.get("_id"))
        if document is None and kwargs.get("upsert"):
            document = {"_id": query["_id"], **copy.deepcopy(update.get("$setOnInsert", {}))}
            self.documents[query["_id"]] = document
        if document is None:
            return SimpleNamespace(matched_count=0)
        for field in ("lease_owner", "refresh_generation"):
            if field in query and not self._matches_value(document.get(field), query[field]):
                return SimpleNamespace(matched_count=0)
        if "$and" in query and not self._eligible(document):
            return SimpleNamespace(matched_count=0)
        document.update(copy.deepcopy(update.get("$set", {})))
        for field, amount in update.get("$inc", {}).items():
            document[field] = int(document.get(field) or 0) + int(amount)
        for field in update.get("$unset", {}):
            document.pop(field, None)
        return SimpleNamespace(matched_count=1)

    async def find_one_and_update(self, query, update, **_kwargs):
        document = self.documents.get(query.get("_id"))
        if document is None:
            return None
        lease = document.get("lease_until")
        if isinstance(lease, datetime) and lease > console.utcnow():
            return None
        document.update(copy.deepcopy(update.get("$set", {})))
        for field, amount in update.get("$inc", {}).items():
            document[field] = int(document.get(field) or 0) + int(amount)
        return copy.deepcopy(document)


class _ContextRecoveryTickets:
    def __init__(self, documents):
        self.documents = {item["_id"]: copy.deepcopy(item) for item in documents}
        self.query = None

    async def find_one(self, query):
        document = self.documents.get(query.get("_id"))
        if (
            document
            and document.get("type") == query.get("type")
            and document.get("venue") == query.get("venue")
            and (
                "status" not in query
                or document.get("status") == query.get("status")
            )
        ):
            return copy.deepcopy(document)
        return None

    def find(self, query):
        self.query = copy.deepcopy(query)
        return _ContextRecoveryCursor(self.documents.values())


class _OpenContextSweepTickets(_ContextRecoveryTickets):
    def find(self, query):
        self.query = copy.deepcopy(query)
        after = (query.get("_id") or {}).get("$gt")
        documents = [
            item
            for item in self.documents.values()
            if item.get("type") == query.get("type")
            and item.get("venue") == query.get("venue")
            and item.get("status") == query.get("status")
            and (after is None or item.get("_id", "") > after)
        ]
        return _ContextRecoveryCursor(documents)


def _assert_component_limits(view):
    nodes = _nodes(view)
    component_nodes = [node for node in nodes if "type" in node]
    assert len(component_nodes) <= 40
    custom_ids = [str(node["custom_id"]) for node in nodes if "custom_id" in node]
    assert len(custom_ids) == len(set(custom_ids))
    for custom_id in custom_ids:
        assert len(custom_id) <= 100
        assert custom_id.count(":") == 1
    text_contents = [str(node["content"]) for node in nodes if "content" in node]
    assert sum(len(content) for content in text_contents) <= (
        console.DISCORD_MESSAGE_TEXT_LIMIT
    )
    for node in nodes:
        if "content" in node:
            assert 1 <= len(str(node["content"])) <= 4000
        if "label" in node:
            assert len(str(node["label"])) <= 100
        options = node.get("options")
        if options is not None:
            assert 1 <= len(options) <= 25
            assert int(node.get("max_values", 1)) <= len(options)


@pytest.mark.parametrize(
    ("raw", "kind", "value", "error"),
    [
        ("", "all", "", False),
        ("223456789012345678", "discord_id", "223456789012345678", False),
        ("123", "invalid", "123", True),
        ("#abc123", "player_tag", "#ABC123", False),
        ("#x", "invalid", "#x", True),
        ("Some.User-2", "username", "Some.User-2", False),
        ("a", "invalid", "a", True),
    ],
)
def test_search_validation_matches_the_decided_three_inputs(raw, kind, value, error):
    parsed = console.parse_search_query(raw)
    assert (parsed.kind, parsed.value, bool(parsed.error)) == (kind, value, error)


def test_archived_ticket_jump_is_a_plain_url_and_never_an_unarchive_action():
    document = _ticket(7)
    assert console.ticket_jump_url(document) == (
        "https://discord.com/channels/123456789012345678/323456789012345685"
    )
    assert console.ticket_jump_url(document, staff=True) == (
        "https://discord.com/channels/123456789012345678/423456789012345685"
    )


def _hub_picker_component(container):
    return next(
        child["components"][0]
        for child in container["components"]
        if child["type"] == hikari.ComponentType.ACTION_ROW
        and child["components"][0].get("custom_id") == "ticket_v2_console_pick:hub"
    )


def test_shared_hub_has_native_overview_status_picker_and_actions():
    view = console.build_hub_components([_ticket(index) for index in range(1, 26)], b"png")
    container, attachments = view[0].build()

    assert [child["type"] for child in container["components"][:3]] == [
        hikari.ComponentType.TEXT_DISPLAY,
        hikari.ComponentType.MEDIA_GALLERY,
        hikari.ComponentType.SEPARATOR,
    ]
    assert container["components"][0]["content"] == "# Ticket Console"
    assert [attachment.filename for attachment in attachments] == [
        "ticket_overview.png", "clan_main.png", "ticket_main_status.png",
        "clan_fwa.png", "ticket_fwa_status.png",
    ]
    assert sum(child["type"] == hikari.ComponentType.SECTION for child in container["components"]) == 2
    assert sum(child["type"] == hikari.ComponentType.MEDIA_GALLERY for child in container["components"]) == 3
    assert len(attachments) == 5
    select = _hub_picker_component(container)
    assert len(select["options"]) == 25
    assert all(option["value"].startswith("ticket_") for option in select["options"])
    buttons = next(
        child["components"]
        for child in container["components"]
        if child["type"] == hikari.ComponentType.ACTION_ROW
        and child["components"][0].get("custom_id") == "ticket_v2_console_find:hub"
    )
    assert [button["custom_id"] for button in buttons] == [
        "ticket_v2_console_find:hub",
        "ticket_v2_console_browse:hub",
    ]
    assert buttons[1]["label"] == "Browse tickets"
    assert container["components"][-2]["type"] == hikari.ComponentType.SEPARATOR
    assert "tickets** · Main" in container["components"][-1]["content"]
    contents = [child.get("content", "") for child in container["components"]]
    assert "🔴 **0 blacklisted**" in contents
    assert "🟡 **0 denied before**" in contents
    assert "🟠 **0 not loyal to WU**" in contents
    flag_indices = [
        index for index, child in enumerate(container["components"])
        if child.get("content", "").startswith(("🔴", "🟡", "🟠"))
    ]
    assert len(flag_indices) == 3
    assert all(container["components"][index]["type"] == hikari.ComponentType.TEXT_DISPLAY for index in flag_indices)
    assert [container["components"][index + 1]["type"] for index in flag_indices[:2]] == [
        hikari.ComponentType.SEPARATOR, hikari.ComponentType.SEPARATOR,
    ]
    _assert_component_limits(view)


def test_hub_payload_prewarms_all_thumbnail_decoding_off_the_gateway_loop(monkeypatch):
    calls = []

    async def list_open(_mongo, *, limit):
        assert limit == console.MAX_OPEN_PICKER
        return []

    async def counts(_mongo):
        return {"statuses": {"open": 0}, "by_type": {"main": {}, "fwa": {}}}

    async def flags(_mongo):
        return {}

    async def strip(_counts):
        return b"strip"

    async def bar(_values, *, maximum):
        assert maximum == 1
        return b"bar"

    async def to_thread(function, *args, **kwargs):
        calls.append((function, args))
        return {filename: b"thumbnail" for filename in console.HUB_THUMBNAIL_FILENAMES}

    monkeypatch.setattr(console.store, "list_open", list_open)
    monkeypatch.setattr(console.store, "console_counts", counts)
    monkeypatch.setattr(console.flag_store, "count_active", flags)
    monkeypatch.setattr(console, "render_status_strip", strip)
    monkeypatch.setattr(console, "render_clan_status_bar", bar)
    monkeypatch.setattr(console.asyncio, "to_thread", to_thread)

    view = asyncio.run(console._hub_payload(object()))

    assert calls == [(console._hub_thumbnail_assets, ())]
    _assert_component_limits(view)


def test_hub_picker_with_more_than_25_open_shows_oldest_and_says_how_many():
    """The picker only ever holds 25 options. Given an oldest-first list (as
    `store.list_open` now returns) of 30 open tickets, the 25 shown must be
    the 25 oldest -- not the 25 newest, which would drop the
    longest-waiting applicants off the list -- and the placeholder must
    tell the recruiter there are more."""
    tickets = [_ticket(index) for index in range(1, 31)]  # oldest (1) first
    view = console.build_hub_components(tickets, b"png", total_open=30)
    container, _attachments = view[0].build()

    select = _hub_picker_component(container)
    assert len(select["options"]) == 25
    shown_ids = {option["value"] for option in select["options"]}
    assert shown_ids == {console._ticket_id(_ticket(index)) for index in range(1, 26)}
    assert select["placeholder"] == (
        "Choose a ticket (25 of 30 shown, oldest first; use Find for the rest)"
    )
    _assert_component_limits(view)


def test_hub_clan_lines_keep_closed_counts_native_when_present():
    counts = console.OverviewCounts(
        statuses={"closed": 3},
        by_type={"main": {"closed": 3}, "fwa": {}},
        flags={},
    )

    view = console.build_hub_components([], b"png", counts=counts)
    contents = [str(node["content"]) for node in _nodes(view) if "content" in node]

    assert any("3 closed / no decision" in content for content in contents)
    _assert_component_limits(view)


def test_hub_picker_placeholder_stays_plain_when_25_or_fewer_open():
    tickets = [_ticket(index) for index in range(1, 26)]
    view = console.build_hub_components(tickets, b"png", total_open=25)
    container, _attachments = view[0].build()
    select = _hub_picker_component(container)
    assert select["placeholder"] == "Choose an open ticket"


def test_empty_hub_keeps_a_valid_disabled_picker():
    view = console.build_hub_components([], b"png")
    container, _attachments = view[0].build()
    select = _hub_picker_component(container)
    assert select["disabled"] is True
    assert [option["label"] for option in select["options"]] == ["No open tickets"]
    _assert_component_limits(view)


def test_hub_picker_option_label_is_not_markdown_escaped():
    """Select-option labels are plain text Discord never renders as
    markdown, so `_escape_markdown`'s backslashes would show up literally
    instead of staying inert."""
    ticket = _ticket(1, username="_Weird*Name_")
    view = console.build_hub_components([ticket], b"png")
    container, _attachments = view[0].build()
    select = _hub_picker_component(container)

    assert select["options"][0]["label"] == "FWA #1 · _Weird*Name_"
    assert "\\" not in select["options"][0]["label"]


def test_search_worst_case_uses_exact_safe_budget_and_unknown_status_fallback():
    results = [_ticket(index) for index in range(1, 11)]
    results[-1]["status"] = "legacy_unknown"
    view = console.build_search_panel(
        "a" * 32,
        "Applicant",
        ("open", "approved", "denied"),
        ("main", "fwa"),
        results,
        view_action_ids=[f"{index:032x}" for index in range(10)],
    )
    assert len(_component_nodes(view)) == console.SEARCH_PANEL_COMPONENT_MAX == 40
    assert "Legacy Unknown" in "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert not [node["url"] for node in _nodes(view) if "url" in node]
    view_buttons = [
        node for node in _nodes(view)
        if str(node.get("custom_id", "")).startswith("ticket_v2_console_view:")
    ]
    assert len(view_buttons) == 10
    assert any(node.get("label") == "New search" for node in _nodes(view))
    _assert_component_limits(view)


def test_search_heading_shows_the_actual_number_rendered():
    """A fixed "newest 10 matches" hid how many results there actually were
    -- 3 out of 3 looked identical to 3 out of 300. The heading must show
    the true count, and say how much is hidden only when it is truncated."""
    few = console.build_search_panel(
        "a" * 32, "", (), (), [_ticket(index) for index in range(1, 4)],
    )
    exact = console.build_search_panel(
        "a" * 32, "", (), (), [_ticket(index) for index in range(1, 11)], total=10,
    )
    truncated = console.build_search_panel(
        "a" * 32, "", (), (), [_ticket(index) for index in range(1, 11)], total=27,
    )

    def _summary(view):
        return next(
            str(node["content"]) for node in _nodes(view) if "content" in node
        ).splitlines()[1]

    assert _summary(few) == "All tickets · 3 matches"
    assert _summary(exact) == "All tickets · 10 matches"
    assert _summary(truncated) == "All tickets · newest 10 of 27 matches"


def test_browse_panel_renders_ten_rows_status_type_period_selects_and_open_picker():
    results = [_ticket(index) for index in range(1, 11)]
    view = console.build_browse_panel(
        "a" * 32,
        status="all",
        ticket_type="all",
        period="all",
        page=1,
        total_pages=3,
        results=results,
        total=27,
    )
    nodes = _nodes(view)
    contents = [str(node["content"]) for node in nodes if "content" in node]
    assert "Page 1 of 3 · 27 tickets" in contents[0]

    list_text = next(text for text in contents if text.count("\n") == 9)
    assert list_text.count("\n") == 9  # 10 rows joined by 9 newlines
    for ticket_doc in results:
        assert console._ticket_label(ticket_doc) in list_text

    selects = [node for node in nodes if node.get("type") == hikari.ComponentType.TEXT_SELECT_MENU]
    # status, type, period, and the "Open a ticket" picker
    assert len(selects) == 4
    picker = next(
        select for select in selects
        if str(select["custom_id"]).startswith("ticket_v2_console_browse_pick:")
    )
    assert len(picker["options"]) == 10
    assert all(option["value"].startswith("ticket_") for option in picker["options"])

    buttons = [node for node in nodes if node.get("type") == hikari.ComponentType.BUTTON]
    prev_button = next(b for b in buttons if str(b["custom_id"]).endswith("|prev"))
    next_button = next(b for b in buttons if str(b["custom_id"]).endswith("|next"))
    assert prev_button["disabled"] is True
    assert next_button["disabled"] is False
    _assert_component_limits(view)


def test_browse_panel_disables_next_on_last_page_and_prev_stays_enabled():
    view = console.build_browse_panel(
        "a" * 32,
        status="open",
        ticket_type="main",
        period="7",
        page=3,
        total_pages=3,
        results=[_ticket(1)],
        total=21,
    )
    nodes = _nodes(view)
    buttons = [node for node in nodes if node.get("type") == hikari.ComponentType.BUTTON]
    prev_button = next(b for b in buttons if str(b["custom_id"]).endswith("|prev"))
    next_button = next(b for b in buttons if str(b["custom_id"]).endswith("|next"))
    assert prev_button["disabled"] is False
    assert next_button["disabled"] is True


def test_browse_panel_with_no_results_disables_the_open_picker():
    view = console.build_browse_panel(
        "a" * 32,
        status="denied",
        ticket_type="all",
        period="all",
        page=1,
        total_pages=1,
        results=[],
        total=0,
    )
    nodes = _nodes(view)
    contents = [str(node["content"]) for node in nodes if "content" in node]
    assert "No tickets match those filters." in contents
    picker = next(
        node for node in nodes
        if node.get("type") == hikari.ComponentType.TEXT_SELECT_MENU
        and str(node["custom_id"]).startswith("ticket_v2_console_browse_pick:")
    )
    assert picker["disabled"] is True
    assert picker["options"][0]["value"] == "no-browse-tickets"
    _assert_component_limits(view)


def test_browse_status_options_include_closed_with_a_grey_accent():
    # Bulk-migration follow-up rule 6: Closed joins the Browse status select.
    values = [value for value, _label, _emoji in console.BROWSE_STATUS_OPTIONS]
    assert "closed" in values
    label, _emoji, accent = console._status_meta("closed")
    assert label == "Closed · no decision recorded"
    assert accent == console.ACCENT_GREY


def test_browse_panel_status_select_offers_a_closed_option():
    view = console.build_browse_panel(
        "a" * 32,
        status="closed",
        ticket_type="all",
        period="all",
        page=1,
        total_pages=1,
        results=[_ticket(1, status="closed")],
        total=1,
    )
    nodes = _nodes(view)
    status_select = next(
        node for node in nodes
        if node.get("type") == hikari.ComponentType.TEXT_SELECT_MENU
        and str(node["custom_id"]).startswith("ticket_v2_console_browse_status:")
    )
    option_values = [option["value"] for option in status_select["options"]]
    assert "closed" in option_values
    selected = next(option for option in status_select["options"] if option["value"] == "closed")
    assert selected["default"] is True


def test_browse_row_line_shows_closed_no_decision():
    ticket_doc = _ticket(1, status="closed")
    # `_browse_row_line` renders `_ticket_label` plus the status via
    # `_status_meta`, so this also proves `_ticket_label` did not choke on
    # the new status value.
    assert "Closed · no decision recorded" in console._browse_row_line(ticket_doc)


def test_browse_total_pages_and_clamp_page_are_pure_pagination_math():
    assert console._browse_total_pages(0, 10) == 1
    assert console._browse_total_pages(10, 10) == 1
    assert console._browse_total_pages(11, 10) == 2
    assert console._browse_total_pages(27, 10) == 3

    assert console._clamp_browse_page(1, 3) == 1
    assert console._clamp_browse_page(0, 3) == 1
    assert console._clamp_browse_page(-5, 3) == 1
    assert console._clamp_browse_page(3, 3) == 3
    assert console._clamp_browse_page(9, 3) == 3


def test_render_browse_session_clamps_page_and_persists_it(monkeypatch):
    events = []

    async def browse_count(_mongo, **kwargs):
        events.append(("count", kwargs))
        return 5  # only 1 page at page_size=10

    async def browse(_mongo, **kwargs):
        events.append(("browse", kwargs))
        return [_ticket(index) for index in range(1, 6)]

    async def update(_mongo, action_id, update_doc, **_kwargs):
        events.append(("update", action_id, update_doc))

    monkeypatch.setattr(console.store, "browse_count", browse_count)
    monkeypatch.setattr(console.store, "browse", browse)
    monkeypatch.setattr(console, "update_state", update)

    view = asyncio.run(console._render_browse_session(
        object(),
        action_id="abc",
        owner_id=22,
        guild_id=33,
        status="all",
        ticket_type="all",
        period="all",
        page=9,  # far beyond the single available page
    ))

    kinds = [event[0] for event in events]
    assert kinds == ["count", "browse", "update"]
    assert events[2][1:] == ("abc", {"$set": {"page": 1}})
    contents = [str(node["content"]) for node in _nodes(view) if "content" in node]
    assert "Page 1 of 1 · 5 tickets" in contents[0]


def test_browse_status_filter_updates_state_and_resets_page(monkeypatch):
    events = []

    class Interaction:
        values = ("open",)

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def update(_mongo, action_id, update_doc, **_kwargs):
        events.append(("update", action_id, update_doc))

    async def render(_mongo, **kwargs):
        events.append(("render", kwargs))
        return ["RENDERED"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "update_state", update)
    monkeypatch.setattr(console, "_render_browse_session", render)

    result = asyncio.run(console.ticket_console_browse_status(
        Context(), "abc",
        owner_id=22, guild_id=33,
        status="all", ticket_type="fwa", period="30", page=2,
        mongo=object(),
    ))

    assert result == ["RENDERED"]
    assert events[0] == ("update", "abc", {"$set": {"status": "open", "page": 1}})
    assert events[1][1] == {
        "action_id": "abc",
        "owner_id": 22,
        "guild_id": 33,
        "status": "open",
        "ticket_type": "fwa",
        "period": "30",
        "page": 1,
        "custom_from": None,
        "custom_to": None,
    }


def test_browse_filter_re_renders_unchanged_panel_when_not_recruiter(monkeypatch):
    class Context:
        user = SimpleNamespace(id=22)
        member = object()

        async def respond(self, *args, **kwargs):
            responses.append((args, kwargs))

    responses = []

    async def denied(_member, _mongo):
        return False

    async def render(_mongo, **kwargs):
        assert kwargs == {
            "action_id": "abc",
            "owner_id": 22,
            "guild_id": 33,
            "status": "open",
            "ticket_type": "all",
            "period": "all",
            "page": 2,
            "custom_from": None,
            "custom_to": None,
        }
        return ["UNCHANGED"]

    monkeypatch.setattr(console.perms, "is_recruiter", denied)
    monkeypatch.setattr(console, "_render_browse_session", render)

    result = asyncio.run(console.ticket_console_browse_type(
        Context(), "abc",
        owner_id=22, guild_id=33,
        status="open", ticket_type="all", period="all", page=2,
        mongo=object(),
    ))
    assert result == ["UNCHANGED"]
    assert len(responses) == 1
    assert "Only recruiters" in responses[0][0][0]


def test_browse_page_button_advances_and_retreats_with_a_floor_of_one(monkeypatch):
    events = []
    state = {
        "type": "ticket_v2_console_browse",
        "owner_id": 22,
        "guild_id": 33,
        "status": "all",
        "ticket_type": "all",
        "period": "all",
        "page": 1,
    }

    class Context:
        user = SimpleNamespace(id=22)
        member = object()

    async def get(_mongo, action_id, _projection):
        events.append(("get", action_id))
        return dict(state)

    async def allowed(_member, _mongo):
        return True

    async def update(_mongo, action_id, update_doc, **_kwargs):
        events.append(("update", action_id, update_doc))

    async def render(_mongo, **kwargs):
        events.append(("render", kwargs["page"]))
        return ["RENDERED"]

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "update_state", update)
    monkeypatch.setattr(console, "_render_browse_session", render)

    # Prev on page 1 must not go below 1.
    asyncio.run(console.ticket_console_browse_page(Context(), "abc|prev", mongo=object()))
    assert events[1] == ("update", "abc", {"$set": {"page": 1}})
    assert events[2] == ("render", 1)

    events.clear()
    asyncio.run(console.ticket_console_browse_page(Context(), "abc|next", mongo=object()))
    assert events[1] == ("update", "abc", {"$set": {"page": 2}})
    assert events[2] == ("render", 2)


def test_browse_page_button_reports_expired_when_state_is_gone(monkeypatch):
    async def get(_mongo, _action_id, _projection):
        return None

    monkeypatch.setattr(console, "get_state", get)

    view = asyncio.run(console.ticket_console_browse_page(
        SimpleNamespace(user=SimpleNamespace(id=22)), "abc|next", mongo=object(),
    ))
    contents = [str(node["content"]) for node in _nodes(view) if "content" in node]
    assert contents[0] == "## Browse expired"


def test_browse_pick_opens_the_ticket_detail_panel(monkeypatch):
    ticket = _ticket(3)

    class Interaction:
        values = (ticket["_id"],)

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def find_one(_mongo, query):
        assert query == {"_id": ticket["_id"], "type": "ticket"}
        return ticket

    async def detail(_mongo, ticket_doc, **kwargs):
        assert ticket_doc is ticket
        assert kwargs == {"owner_id": 22, "guild_id": 33}
        return ["DETAIL"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console.store, "find_one", find_one)
    monkeypatch.setattr(console, "_ticket_detail_panel", detail)

    result = asyncio.run(console.ticket_console_browse_pick(
        Context(), "abc", owner_id=22, guild_id=33, mongo=object(),
    ))
    assert result == ["DETAIL"]


def test_browse_pick_rejects_a_panel_that_belongs_to_someone_else():
    result = asyncio.run(console.ticket_console_browse_pick(
        SimpleNamespace(user=SimpleNamespace(id=99)),
        "abc", owner_id=22, guild_id=33, mongo=object(),
    ))
    contents = [str(node["content"]) for node in _nodes(result) if "content" in node]
    assert contents[0] == "## Private panel"


def test_browse_button_opens_a_fresh_ephemeral_panel(monkeypatch):
    followups = []

    class Interaction:
        async def execute(self, **kwargs):
            followups.append(kwargs)

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

    async def allowed(_member, _mongo):
        return True

    async def create_state(_mongo, *, owner_id, guild_id):
        assert (owner_id, guild_id) == (22, 33)
        return "browse-1"

    async def render(_mongo, **kwargs):
        assert kwargs == {
            "action_id": "browse-1",
            "owner_id": 22,
            "guild_id": 33,
            "status": "all",
            "ticket_type": "all",
            "period": "all",
            "page": 1,
        }
        return ["PANEL"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "_create_browse_state", create_state)
    monkeypatch.setattr(console, "_render_browse_session", render)

    asyncio.run(console.ticket_console_browse(Context(), "hub", mongo=object()))

    assert len(followups) == 1
    assert followups[0]["components"] == ["PANEL"]
    assert followups[0]["flags"] & hikari.MessageFlag.EPHEMERAL


def test_browse_actions_are_registered_with_the_right_dispatcher_shape():
    browse = dispatcher.registered_functions["ticket_v2_console_browse"]
    assert browse.no_return is True

    status = dispatcher.registered_functions["ticket_v2_console_browse_status"]
    assert status.requires_state is True
    type_action = dispatcher.registered_functions["ticket_v2_console_browse_type"]
    assert type_action.requires_state is True
    period = dispatcher.registered_functions["ticket_v2_console_browse_period"]
    assert period.requires_state is True

    page = dispatcher.registered_functions["ticket_v2_console_browse_page"]
    assert page.preload_state is False

    pick = dispatcher.registered_functions["ticket_v2_console_browse_pick"]
    assert pick.requires_state is True

    for name in (
        "ticket_v2_console_browse_custom",
        "ticket_v2_console_browse_custom_from_year",
        "ticket_v2_console_browse_custom_from_month",
        "ticket_v2_console_browse_custom_to_year",
        "ticket_v2_console_browse_custom_to_month",
        "ticket_v2_console_browse_custom_apply",
        "ticket_v2_console_browse_custom_cancel",
    ):
        assert dispatcher.registered_functions[name].requires_state is True


def test_browse_since_returns_month_bounds_for_a_custom_range():
    since, until = console._browse_since("custom", "2025-06", "2025-06")
    assert since == datetime(2025, 6, 1, tzinfo=timezone.utc)
    assert until == datetime(2025, 7, 1, tzinfo=timezone.utc)


def test_browse_since_custom_range_rolls_december_into_next_january():
    since, until = console._browse_since("custom", "2025-11", "2025-12")
    assert since == datetime(2025, 11, 1, tzinfo=timezone.utc)
    assert until == datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_browse_since_presets_have_no_until():
    since, until = console._browse_since("30")
    assert until is None
    assert since is not None

    since, until = console._browse_since("all")
    assert since is None
    assert until is None


def test_browse_period_label_formats_a_custom_range_and_falls_back_otherwise():
    assert console._browse_period_label("custom", "2025-06", "2025-08") == "Custom: Jun 2025 – Aug 2025"
    assert console._browse_period_label("custom", None, None) == "Custom range…"
    assert console._browse_period_label("all", None, None) == "All time"


def test_build_browse_custom_panel_renders_four_selects_and_apply_cancel_buttons():
    view = console.build_browse_custom_panel(
        "a" * 32,
        year_options=(("2025", "2025", "🗓️"), ("2026", "2026", "🗓️")),
        from_year="2025", from_month="6", to_year="2026", to_month="1",
    )
    nodes = _nodes(view)
    contents = [str(node["content"]) for node in nodes if "content" in node]
    assert contents[0] == "## Browse tickets · Custom range"

    selects = [node for node in nodes if node.get("type") == hikari.ComponentType.TEXT_SELECT_MENU]
    assert len(selects) == 4
    placeholders = {str(s["custom_id"]).split(":")[0]: s["placeholder"] for s in selects}
    assert placeholders["ticket_v2_console_browse_custom_from_year"] == "From year"
    assert placeholders["ticket_v2_console_browse_custom_from_month"] == "From month"
    assert placeholders["ticket_v2_console_browse_custom_to_year"] == "To year"
    assert placeholders["ticket_v2_console_browse_custom_to_month"] == "To month"

    buttons = [node for node in nodes if node.get("type") == hikari.ComponentType.BUTTON]
    assert {b["label"] for b in buttons} == {"Apply", "Cancel"}
    assert view[0].accent_color == console.ACCENT_BLUE
    _assert_component_limits(view)


def test_build_browse_custom_panel_shows_an_inline_error_with_red_accent():
    view = console.build_browse_custom_panel(
        "a" * 32,
        year_options=(("2025", "2025", "🗓️"),),
        from_year="2025", from_month="8", to_year="2025", to_month="6",
        error="The From month must be on or before the To month.",
    )
    contents = [str(node["content"]) for node in _nodes(view) if "content" in node]
    assert any("must be on or before" in text for text in contents)
    assert view[0].accent_color == console.ACCENT_RED
    _assert_component_limits(view)


def test_browse_period_custom_choice_enters_custom_mode(monkeypatch):
    events = []

    class Interaction:
        values = ("custom",)

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def custom_entry(_ctx, action_id, *, owner_id, guild_id, status, ticket_type, custom_from, custom_to, mongo):
        events.append((action_id, owner_id, guild_id, status, ticket_type, custom_from, custom_to))
        return ["CUSTOM_PANEL"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "ticket_console_browse_custom", custom_entry)

    result = asyncio.run(console.ticket_console_browse_period(
        Context(), "abc",
        owner_id=22, guild_id=33,
        status="open", ticket_type="fwa", period="all", page=2,
        mongo=object(),
    ))

    assert result == ["CUSTOM_PANEL"]
    assert events == [("abc", 22, 33, "open", "fwa", None, None)]


def test_browse_custom_entry_seeds_state_defaults_and_renders_the_editor(monkeypatch):
    events = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def update(_mongo, action_id, update_doc, **_kwargs):
        events.append(("update", action_id, update_doc))

    async def render_custom(_mongo, **kwargs):
        events.append(("render", kwargs))
        return ["EDITOR"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "update_state", update)
    monkeypatch.setattr(console, "_render_browse_custom_panel", render_custom)
    monkeypatch.setattr(console, "utcnow", lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    result = asyncio.run(console.ticket_console_browse_custom(
        Context(), "abc", owner_id=22, guild_id=33,
        status="open", ticket_type="all",
        mongo=object(),
    ))

    assert result == ["EDITOR"]
    assert events[0] == (
        "update", "abc",
        {"$set": {
            "custom_from_year": "2026", "custom_from_month": "9",
            "custom_to_year": "2026", "custom_to_month": "9",
        }},
    )
    assert events[1][1] == {
        "action_id": "abc",
        "from_year": "2026", "from_month": "9",
        "to_year": "2026", "to_month": "9",
    }


def test_browse_custom_entry_reuses_an_already_applied_range_when_reopened(monkeypatch):
    events = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def update(_mongo, _action_id, update_doc, **_kwargs):
        events.append(update_doc)

    async def render_custom(_mongo, **_kwargs):
        return ["EDITOR"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "update_state", update)
    monkeypatch.setattr(console, "_render_browse_custom_panel", render_custom)

    asyncio.run(console.ticket_console_browse_custom(
        Context(), "abc", owner_id=22, guild_id=33,
        custom_from="2025-06", custom_to="2025-08",
        mongo=object(),
    ))

    assert events[0] == {"$set": {
        "custom_from_year": "2025", "custom_from_month": "6",
        "custom_to_year": "2025", "custom_to_month": "8",
    }}


def test_browse_custom_from_year_select_updates_one_field_and_stays_in_the_editor(monkeypatch):
    events = []

    class Interaction:
        values = ("2024",)

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def update(_mongo, action_id, update_doc, **_kwargs):
        events.append(("update", action_id, update_doc))

    async def render_custom(_mongo, **kwargs):
        events.append(("render", kwargs))
        return ["EDITOR"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "update_state", update)
    monkeypatch.setattr(console, "_render_browse_custom_panel", render_custom)

    result = asyncio.run(console.ticket_console_browse_custom_from_year(
        Context(), "abc", owner_id=22, guild_id=33,
        custom_from_year="2025", custom_from_month="6",
        custom_to_year="2025", custom_to_month="8",
        mongo=object(),
    ))

    assert result == ["EDITOR"]
    assert events[0] == ("update", "abc", {"$set": {"custom_from_year": "2024"}})
    assert events[1][1] == {
        "action_id": "abc",
        "from_year": "2024", "from_month": "6", "to_year": "2025", "to_month": "8",
    }


def test_browse_custom_apply_rejects_from_after_to_with_an_inline_error(monkeypatch):
    update_events = []
    render_events = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def update(_mongo, action_id, update_doc, **_kwargs):
        update_events.append(update_doc)

    async def render_custom(_mongo, **kwargs):
        render_events.append(kwargs)
        return ["ERROR_VIEW"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "update_state", update)
    monkeypatch.setattr(console, "_render_browse_custom_panel", render_custom)

    result = asyncio.run(console.ticket_console_browse_custom_apply(
        Context(), "abc", owner_id=22, guild_id=33,
        status="open", ticket_type="fwa",
        custom_from_year="2025", custom_from_month="8",
        custom_to_year="2025", custom_to_month="6",
        mongo=object(),
    ))

    assert result == ["ERROR_VIEW"]
    assert update_events == []  # no state was committed
    assert render_events[0]["error"] == "The From month must be on or before the To month."
    assert render_events[0]["from_year"] == "2025"
    assert render_events[0]["from_month"] == "8"
    assert render_events[0]["to_year"] == "2025"
    assert render_events[0]["to_month"] == "6"


def test_browse_custom_apply_commits_the_range_resets_page_and_shows_the_placeholder(monkeypatch):
    events = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def update(_mongo, action_id, update_doc, **_kwargs):
        events.append(update_doc)

    async def browse_count(_mongo, **_kwargs):
        return 3

    async def browse(_mongo, **_kwargs):
        return [_ticket(index) for index in range(1, 4)]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "update_state", update)
    monkeypatch.setattr(console.store, "browse_count", browse_count)
    monkeypatch.setattr(console.store, "browse", browse)

    result = asyncio.run(console.ticket_console_browse_custom_apply(
        Context(), "abc", owner_id=22, guild_id=33,
        status="open", ticket_type="fwa",
        custom_from_year="2025", custom_from_month="6",
        custom_to_year="2025", custom_to_month="8",
        mongo=object(),
    ))

    assert events[0] == {"$set": {
        "period": "custom", "custom_from": "2025-06", "custom_to": "2025-08", "page": 1,
    }}
    contents = [str(node["content"]) for node in _nodes(result) if "content" in node]
    assert "Custom: Jun 2025 – Aug 2025" in contents[0]


def test_browse_custom_cancel_restores_the_previous_period(monkeypatch):
    events = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()

    async def allowed(_member, _mongo):
        return True

    async def render(_mongo, **kwargs):
        events.append(kwargs)
        return ["LIST"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "_render_browse_session", render)

    result = asyncio.run(console.ticket_console_browse_custom_cancel(
        Context(), "abc", owner_id=22, guild_id=33,
        status="open", ticket_type="fwa", period="30", page=2,
        custom_from=None, custom_to=None,
        custom_from_year="2025", custom_from_month="6",
        custom_to_year="2025", custom_to_month="8",
        mongo=object(),
    ))

    assert result == ["LIST"]
    assert events[0] == {
        "action_id": "abc", "owner_id": 22, "guild_id": 33,
        "status": "open", "ticket_type": "fwa", "period": "30", "page": 2,
        "custom_from": None, "custom_to": None,
    }


def test_browse_custom_year_range_derives_from_the_oldest_ticket(monkeypatch):
    async def find(_mongo, _filt, *, sort=None, limit=None):
        assert sort == [("created_at", 1)]
        assert limit == 1
        return [_ticket(1, created_at=datetime(2023, 3, 1, tzinfo=timezone.utc))]

    monkeypatch.setattr(console.store, "find", find)
    monkeypatch.setattr(console, "utcnow", lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    start_year, end_year = asyncio.run(console._browse_custom_year_range(object()))
    assert (start_year, end_year) == (2023, 2026)


def test_browse_custom_year_range_falls_back_to_the_current_year_with_no_tickets(monkeypatch):
    async def find(_mongo, _filt, *, sort=None, limit=None):
        return []

    monkeypatch.setattr(console.store, "find", find)
    monkeypatch.setattr(console, "utcnow", lambda: datetime(2026, 9, 9, tzinfo=timezone.utc))

    start_year, end_year = asyncio.run(console._browse_custom_year_range(object()))
    assert (start_year, end_year) == (2026, 2026)


def test_long_notice_reserves_its_heading_inside_the_message_text_budget():
    title = "Important recruiter notice"
    view = console._notice(title, "x" * 4000)

    contents = [str(node["content"]) for node in _nodes(view) if "content" in node]
    assert contents[0] == f"## {title}"
    assert contents[1].endswith("…")
    _assert_component_limits(view)


def test_blacklist_disables_approve_but_keeps_deny_available():
    view = console.build_ticket_detail(
        _ticket(12),
        action_id="b" * 32,
        flags=[{
            "kind": console.flag_store.FLAG_BLACKLISTED,
            "active": True,
            "reason": "Confirmed on FWA Chocolate.",
        }],
        history=[_ticket(2, status="denied", denial_reason="Did not meet the rules")],
    )
    buttons = [
        node for node in _nodes(view)
        if int(node.get("type", -1)) == int(hikari.ComponentType.BUTTON)
    ]
    approve = next(node for node in buttons if node.get("label") == "Approve")
    deny = next(node for node in buttons if node.get("label") == "Deny")
    assert approve["disabled"] is True
    assert deny.get("disabled", False) is False
    assert len([node for node in _nodes(view) if "url" in node]) >= 2
    _assert_component_limits(view)


def test_detail_shows_flag_conflict_notice_and_leaves_approve_enabled():
    """Commit 3: the overlap is surfaced, but only the blacklist gate blocks Approve."""
    ticket = _ticket(
        13,
        status="open",
        linked_accounts={
            "flag_conflict": {
                "flag_ids": ["flag_a", "flag_b"],
                "at": datetime(2026, 9, 1, tzinfo=timezone.utc),
            },
        },
    )
    view = console.build_ticket_detail(
        ticket, action_id="c" * 32, flags=[], history=[],
    )
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Two flags overlap" in content
    assert "flag_a" in content and "flag_b" in content
    buttons = [
        node for node in _nodes(view)
        if int(node.get("type", -1)) == int(hikari.ComponentType.BUTTON)
    ]
    approve = next(node for node in buttons if node.get("label") == "Approve")
    assert approve.get("disabled", False) is False
    _assert_component_limits(view)


def test_detail_bounds_large_flag_sets_without_breaking_component_limits():
    flags = [{
        "_id": f"flag_{index:03d}_" + "x" * 70,
        "kind": (
            console.flag_store.FLAG_BLACKLISTED
            if index == 0 else console.flag_store.FLAG_NOT_LOYAL
        ),
        "active": True,
        "reason": f"Recruiter note {index}: " + "r" * 300,
    } for index in range(50)]
    view = console.build_ticket_detail(
        _ticket(16),
        action_id="e" * 32,
        flags=flags,
        history=[_ticket(index, status="denied") for index in range(1, 6)],
    )
    flag_detail = next(
        str(node["content"])
        for node in _nodes(view)
        if str(node.get("content", "")).startswith("### Staff flags")
    )
    assert len(flag_detail) <= 4000
    assert "additional matching flags not shown" in flag_detail
    _assert_component_limits(view)


def test_detail_bounds_many_player_tags_without_changing_canonical_values():
    tags = [f"#TAG{index:06d}" for index in range(1000)]
    ticket = _ticket(17, player_tags=tags)

    view = console.build_ticket_detail(
        ticket,
        action_id="f" * 32,
        flags=[],
        history=[],
    )
    detail = next(
        str(node["content"])
        for node in _nodes(view)
        if str(node.get("content", "")).startswith("**Status:**")
    )

    assert len(detail) <= 4000
    assert "tags omitted" in detail
    assert ticket["player_tags"] == tags
    _assert_component_limits(view)


def test_detail_shares_one_text_budget_across_all_worst_case_sections():
    tags = [f"#TAG{index:06d}" for index in range(1000)]
    ticket = _ticket(18, player_tags=tags, intake_snapshot={
        f"question_{index}": "a" * 350
        for index in range(8)
    })
    flags = [{
        "_id": f"flag_{index:03d}_" + "x" * 70,
        "kind": (
            console.flag_store.FLAG_BLACKLISTED
            if index == 0 else console.flag_store.FLAG_NOT_LOYAL
        ),
        "active": True,
        "reason": f"Recruiter note {index}: " + "r" * 300,
    } for index in range(50)]
    history = [
        _ticket(index, status="denied", denial_reason="d" * 100)
        for index in range(1, 6)
    ]

    view = console.build_ticket_detail(
        ticket,
        action_id="g" * 32,
        flags=flags,
        history=history,
    )
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )

    assert "### Staff flags" in content
    assert "additional matching flags not shown" in content
    assert "### Captured intake" in content
    assert "tags omitted" in content
    assert "### Earlier tickets" in content
    assert "Approve is blocked" in content
    _assert_component_limits(view)


def test_ticket_detail_manage_flags_panel_binds_37_tags_without_manual_ids():
    ticket = _ticket(
        21,
        player_tags=[f"#T{index:07d}" for index in range(37)],
    )
    detail = console.build_ticket_detail(
        ticket,
        action_id="m" * 32,
        flags=[],
        history=[],
    )
    manage = next(
        node for node in _nodes(detail)
        if node.get("label") == "Manage flags"
    )
    assert manage["custom_id"] == f"ticket_v2_console_manage_flags:{'m' * 32}"

    flags = [{
        "_id": "flag_blacklist",
        "kind": console.flag_store.FLAG_BLACKLISTED,
        "active": True,
        "rev": 4,
        "source": "FWA Chocolate · FWA ban list",
        "reason": "Verified ban-list match",
    }]
    panel = console.build_flag_manager(
        ticket,
        action_id="f" * 32,
        flags=flags,
    )
    content = "\n".join(
        str(node["content"]) for node in _nodes(panel) if "content" in node
    )
    assert "Stored player tags (37)" in content
    assert "flag_blacklist" in content
    assert "Verified ban-list match" in content
    assert "FWA Chocolate" in content
    remove = next(
        node for node in _nodes(panel)
        if str(node.get("custom_id", "")).startswith("ticket_v2_flag_remove:")
    )
    assert remove["options"][0]["value"] == "0"
    assert "flag_blacklist" not in remove["options"][0]["value"]
    _assert_component_limits(detail)
    _assert_component_limits(panel)


def test_flag_remove_option_description_is_not_markdown_escaped():
    """Select-option descriptions are plain text too -- an operator-entered
    flag reason with markdown characters must show up unescaped, not with
    literal backslashes Discord never interprets."""
    ticket = _ticket(21)
    flags = [{
        "_id": "flag_blacklist",
        "kind": console.flag_store.FLAG_BLACKLISTED,
        "active": True,
        "rev": 4,
        "reason": "*repeat* offender (see #general)",
    }]
    panel = console.build_flag_manager(ticket, action_id="f" * 32, flags=flags)
    remove = next(
        node for node in _nodes(panel)
        if str(node.get("custom_id", "")).startswith("ticket_v2_flag_remove:")
    )

    description = remove["options"][0]["description"]
    assert description == "*repeat* offender (see #general)"
    assert "\\" not in description


def test_flag_modal_openers_acknowledge_with_modal_before_state_or_permission(
    monkeypatch,
):
    opened = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

        def __init__(self, custom_id, values=()):
            self.interaction = SimpleNamespace(custom_id=custom_id, values=values)

        async def defer(self, **_kwargs):
            raise AssertionError("a flag modal opener was deferred")

        async def respond_with_modal(self, **kwargs):
            opened.append(kwargs["custom_id"])

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a flag modal opener performed prerequisite work")

    monkeypatch.setattr(dispatcher, "get_state", forbidden)
    monkeypatch.setattr(console.perms, "is_recruiter", forbidden)

    asyncio.run(dispatcher._dispatch(Context(
        f"ticket_v2_flag_set:{'a' * 32}|blacklisted"
    ), object()))
    asyncio.run(dispatcher._dispatch(Context(
        f"ticket_v2_flag_remove:{'a' * 32}", values=("0",)
    ), object()))

    assert opened == [
        f"ticket_v2_flag_set_submit:{'a' * 32}|blacklisted",
        f"ticket_v2_flag_remove_submit:{'a' * 32}|0",
    ]


def test_flag_set_submit_uses_latest_ticket_discord_id_and_all_37_tags(
    monkeypatch,
):
    events = []
    ticket = _ticket(
        22,
        player_tags=[f"#A{index:07d}" for index in range(37)],
    )
    state = {
        "type": "ticket_v2_console_flag_manager",
        "owner_id": 22,
        "guild_id": ticket["guild_id"],
        "ticket_id": ticket["_id"],
        "flag_kinds": {
            kind: [] for kind in console.FLAG_META
        },
        "flag_slots": [],
    }

    class Interaction:
        message = None
        components = [[SimpleNamespace(
            custom_id="reason", value="Verified recruiter evidence",
        )]]

        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22, username="Recruiter")
        member = SimpleNamespace(id=22)
        guild_id = ticket["guild_id"]

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def get(_mongo, _action_id, projection=None):
        events.append(("envelope" if projection else "state", projection))
        if projection:
            return {key: state[key] for key in ("type", "owner_id", "guild_id")}
        return copy.deepcopy(state)

    async def allowed(_member, _mongo):
        events.append(("permission", None))
        return True

    async def latest(_mongo, _query):
        events.append(("ticket", None))
        return copy.deepcopy(ticket)

    async def save(*_args, **kwargs):
        events.append(("save", kwargs))
        return console.flag_store.FlagMutation(console.store.WON, {
            "_id": "flag_saved",
            "kind": kwargs["kind"],
            "discord_ids": [kwargs["discord_ids"]],
            "player_tags": list(kwargs["player_tags"]),
        })

    async def refresh(*_args, **_kwargs):
        events.append(("refresh", None))

    async def panel(*_args, **_kwargs):
        events.append(("panel", None))
        return ["UPDATED"]

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console.store, "find_one", latest)
    monkeypatch.setattr(
        console.flag_store, "set_flag_if_current_authorized", save
    )
    monkeypatch.setattr(console, "_refresh_after_flag_mutation", refresh)
    monkeypatch.setattr(console, "_flag_manager_panel", panel)

    asyncio.run(console.ticket_flag_set_submit(
        Context(),
        f"manager|{console.flag_store.FLAG_NOT_LOYAL}",
        mongo=object(),
        bot=object(),
    ))

    assert events[0] == ("defer", {"ephemeral": True})
    saved = next(value for name, value in events if name == "save")
    assert saved["discord_ids"] == ticket["user_id"]
    assert tuple(saved["player_tags"]) == tuple(ticket["player_tags"])
    assert len(saved["player_tags"]) == 37
    assert saved["expected_flag_id"] is None
    assert saved["expected_rev"] is None
    assert events[-1][0] == "edit"
    assert events[-1][1]["components"] == ["UPDATED"]


def test_flag_remove_submit_resolves_selection_slot_and_audits_reason(monkeypatch):
    events = []
    ticket = _ticket(23)
    state = {
        "type": "ticket_v2_console_flag_manager",
        "owner_id": 22,
        "guild_id": ticket["guild_id"],
        "ticket_id": ticket["_id"],
        "flag_kinds": {},
        "flag_slots": [{"flag_id": "flag_selected", "rev": 7}],
    }

    class Interaction:
        message = None
        components = [[SimpleNamespace(
            custom_id="reason", value="Staff verified this no longer applies",
        )]]

        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22, username="Recruiter")
        member = SimpleNamespace(id=22)
        guild_id = ticket["guild_id"]

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def get(_mongo, _action_id, projection=None):
        if projection:
            return {key: state[key] for key in ("type", "owner_id", "guild_id")}
        return copy.deepcopy(state)

    async def allowed(*_args):
        return True

    async def latest(*_args, **_kwargs):
        return copy.deepcopy(ticket)

    async def matching(*_args, **_kwargs):
        return [{"_id": "flag_selected", "active": True}]

    async def remove(*_args, **kwargs):
        events.append(("remove", (_args, kwargs)))
        return console.flag_store.FlagMutation(console.store.WON, {
            "_id": "flag_selected",
            "active": False,
        })

    async def refresh(*_args, **_kwargs):
        return None

    async def panel(*_args, **_kwargs):
        return ["UPDATED"]

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console.store, "find_one", latest)
    monkeypatch.setattr(console.flag_store, "list_for_identity", matching)
    monkeypatch.setattr(console.flag_store, "deactivate_flag_authorized", remove)
    monkeypatch.setattr(console, "_refresh_after_flag_mutation", refresh)
    monkeypatch.setattr(console, "_flag_manager_panel", panel)

    asyncio.run(console.ticket_flag_remove_submit(
        Context(), "manager|0", mongo=object(), bot=object(),
    ))

    _args, kwargs = next(value for name, value in events if name == "remove")
    assert _args[1] == "flag_selected"
    assert kwargs["expected_rev"] == 7
    assert kwargs["reason"] == "Staff verified this no longer applies"
    assert events[0] == ("defer", {"ephemeral": True})
    assert events[-1][1]["components"] == ["UPDATED"]


@pytest.mark.parametrize(
    ("owner_id", "state_guild", "ctx_guild", "allowed", "expected"),
    [
        (99, 33, 33, True, "Private panel"),
        (22, 44, 33, True, "Flag panel expired"),
        (22, 33, 33, False, "Recruiter access required"),
    ],
)
def test_flag_manager_state_denies_wrong_owner_guild_or_recruiter(
    monkeypatch, owner_id, state_guild, ctx_guild, allowed, expected,
):
    envelope = {
        "type": "ticket_v2_console_flag_manager",
        "owner_id": owner_id,
        "guild_id": state_guild,
    }

    class Context:
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = ctx_guild

    async def get(*_args, **_kwargs):
        return copy.deepcopy(envelope)

    async def permission(*_args, **_kwargs):
        return allowed

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console.perms, "is_recruiter", permission)
    data, error = asyncio.run(console._authorized_flag_manager_state(
        Context(), object(), "manager",
    ))

    assert data is None
    assert expected in str(error[0].build())


def test_history_panel_keeps_newest_entries_within_one_message_text_budget():
    history = [
        _ticket(
            index,
            status="denied",
            username="u" * 80,
            denial_reason="d" * 300,
        )
        for index in range(1, 11)
    ]

    view = console.build_history_panel(223456789012345678, history)

    assert "Main #10" in "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    _assert_component_limits(view)


def test_staff_context_worst_case_payload_has_no_marker_and_stays_within_limit(
    monkeypatch,
):
    ticket = _ticket(19)
    flags = [{
        "_id": f"flag_{index}",
        "kind": console.flag_store.FLAG_NOT_LOYAL,
        "active": True,
        "reason": f"Recruiter note {index}: " + "r" * 500,
    } for index in range(8)]
    history = [
        _ticket(index, status="denied", denial_reason="d" * 100)
        for index in range(1, 6)
    ]

    async def matching_flags(*_args, **_kwargs):
        return flags

    async def prior_tickets(*_args, **_kwargs):
        return history

    monkeypatch.setattr(console.flag_store, "list_for_identity", matching_flags)
    monkeypatch.setattr(console.store, "history_for", prior_tickets)

    view = asyncio.run(console.build_staff_identity_context(object(), ticket))
    assert view is not None
    contents = [
        str(node["content"]) for node in _nodes(view) if "content" in node
    ]

    # No hidden marker line is posted; only visible content is present.
    assert not any("ticket-staff-context:" in content for content in contents)
    assert all("**Why:**" in content for content in contents[1:9])
    _assert_component_limits(view)


def test_staff_context_delivery_recovers_lost_checkpoint_structurally(monkeypatch):
    """A checkpoint lost after Discord already committed the panel must be
    re-found by its visible title -- no marker line is posted for it."""

    class Collection:
        def __init__(self):
            self.document = None

        async def update_one(self, query, update, **_kwargs):
            if self.document is None:
                self.document = {"_id": query["_id"]}
                self.document.update(update.get("$setOnInsert", {}))
            self.document.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                self.document.pop(key, None)
            return SimpleNamespace(matched_count=1)

        async def find_one_and_update(self, _query, update, **_kwargs):
            self.document.update(update.get("$set", {}))
            return dict(self.document)

        async def find_one(self, _query):
            return dict(self.document or {})

    class Messages:
        def __init__(self, messages):
            self.messages = messages

        async def to_list(self):
            return list(self.messages)

    class Rest:
        def __init__(self):
            self.creates = 0
            self.edits = 0
            self.messages = []

        def fetch_messages(self, _channel_id):
            return Messages(self.messages)

        async def create_message(self, **kwargs):
            self.creates += 1
            message = SimpleNamespace(
                id=900,
                author=SimpleNamespace(id=7),
                components=kwargs["components"],
            )
            self.messages.append(message)
            return message

        async def edit_message(self, **_kwargs):
            self.edits += 1

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", "Matched history")

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    collection = Collection()
    rest = Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=collection)
    ticket = _ticket(31)

    first = asyncio.run(console.deliver_staff_identity_context(bot, mongo, ticket))
    assert first == 900
    assert rest.creates == 1
    contents = [
        str(node["content"])
        for message in rest.messages
        for node in _nodes(message.components)
        if "content" in node
    ]
    # No hidden marker line was posted for the fresh panel.
    assert not any("ticket-staff-context:" in content for content in contents)

    # Lose the durable checkpoint entirely, as a crash right after Discord
    # committed the message but before Mongo recorded its id would.
    collection.document.pop("message_id", None)
    collection.document.pop("fingerprint", None)

    second = asyncio.run(console.deliver_staff_identity_context(bot, mongo, ticket))
    assert second == 900
    assert rest.creates == 1


def test_legacy_staff_context_marker_message_is_still_recognised():
    """A panel posted before this change still carries the old marker line;
    the structural finder must keep recognising it so already-open tickets
    keep working."""

    ticket = _ticket(32)
    components = console._notice("Applicant context", "Matched history")
    marker = console._staff_context_marker(ticket["_id"])
    legacy_components = [*components, console.Text(content=f"-# {marker}")]
    message = SimpleNamespace(
        id=901,
        author=SimpleNamespace(id=7),
        components=legacy_components,
    )

    class Messages:
        async def to_list(self):
            return [message]

    rest = SimpleNamespace(fetch_messages=lambda _channel_id: Messages())
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))

    found = asyncio.run(console._find_staff_context_message(bot, 102, marker))
    assert found is message


def test_lock_contention_panel_does_not_claim_a_blacklist_exists():
    view = asyncio.run(console._transition_result_panel(
        console.store.Transition(
            console.store.BLOCKED,
            _ticket(18),
            "applicant identity is being updated; try again",
        ),
        verb="approved",
        mongo=object(),
        owner_id=22,
        guild_id=123456789012345678,
    ))
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Approval not completed" in content
    assert "try again" in content
    assert "blacklist" not in content.casefold()


def test_blocked_panel_flag_id_in_code_span_has_no_backslash_escape():
    view = asyncio.run(console._transition_result_panel(
        console.store.Transition(
            console.store.BLOCKED,
            _ticket(20),
            "blacklisted",
            blocker={"_id": "flag_2PP0JCCLU"},
        ),
        verb="approved",
        mongo=object(),
        owner_id=22,
        guild_id=123456789012345678,
    ))
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "`flag_2PP0JCCLU`" in content
    assert "\\_" not in content


def test_effect_failure_panel_reports_durable_automatic_retry():
    view = asyncio.run(console._transition_result_panel(
        console.store.Transition(
            console.store.EFFECT_FAILED,
            _ticket(19, status="approved"),
            "thread archive is pending",
        ),
        verb="approved",
        mongo=object(),
        owner_id=22,
        guild_id=123456789012345678,
    ))
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Decision recorded; updates retrying" in content
    assert resolve.RESOLUTION_EFFECT_RETRY_MESSAGE in content
    assert "notification failed" not in content.casefold()


def test_already_decided_panel_names_who_and_when_with_an_open_button(monkeypatch):
    saved = {}

    async def insert(_mongo, document):
        saved.update(document)

    monkeypatch.setattr(console, "insert_state", insert)

    ticket = _ticket(
        20,
        status="approved",
        approved_by=999,
        approved_by_name="Lead Recruiter",
        approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
        rev=3,
    )
    view = asyncio.run(console._transition_result_panel(
        console.store.Transition(console.store.LOST, ticket),
        verb="approved",
        mongo=object(),
        owner_id=22,
        guild_id=ticket["guild_id"],
    ))
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Already approved" in content
    # A mention of the recruiter who decided it, never the stored name.
    assert "<@999>" in content
    assert "Lead Recruiter" not in content
    labels = [str(node["label"]) for node in _nodes(view) if "label" in node]
    assert "Open ticket" in labels
    assert saved["type"] == "ticket_v2_console_view"
    assert saved["ticket_id"] == ticket["_id"]
    assert saved["owner_id"] == 22
    _assert_component_limits(view)


def test_detail_renders_structured_intake_then_canonical_answer_fallback():
    structured = _ticket(13, intake_snapshot={
        "town_hall": "TH16",
        "age": "17-25",
        "timezone": "UTC+1",
        "looking_for": "A stable war clan",
    })
    structured_text = "\n".join(
        str(node["content"])
        for node in _nodes(console.build_ticket_detail(
            structured, action_id="c" * 32, flags=[], history=[],
        ))
        if "content" in node
    )
    assert "Captured intake" in structured_text
    assert "**Town Hall:** TH16" in structured_text
    assert "**What they want from a clan:** A stable war clan" in structured_text

    transcript = _ticket(14, answers=[{
        "message_id": 500 + index,
        "kind": "answer",
        "content": f"Candidate answer {index}",
        "at": datetime(2026, 8, 20, 3, index, tzinfo=timezone.utc),
    } for index in range(8)])
    transcript_view = console.build_ticket_detail(
        transcript, action_id="d" * 32, flags=[], history=[],
    )
    transcript_text = "\n".join(
        str(node["content"]) for node in _nodes(transcript_view) if "content" in node
    )
    assert "Latest messages from the applicant" in transcript_text
    assert "Candidate answer 4" not in transcript_text
    assert "Candidate answer 5" in transcript_text
    assert "Candidate answer 7" in transcript_text
    # Newest first.
    assert (
        transcript_text.index("Candidate answer 7")
        < transcript_text.index("Candidate answer 6")
        < transcript_text.index("Candidate answer 5")
    )
    _assert_component_limits(transcript_view)


def test_transcript_shows_only_newest_three_and_trims_a_long_line():
    """Point 2 of the recruiter-console noise fix: only the last 3 applicant
    messages render, newest first, each collapsed to one line of at most
    120 characters with an ellipsis when trimmed."""
    long_line = "x" * 200
    ticket = _ticket(15, answers=[{
        "message_id": 600 + index,
        "kind": "answer",
        "content": long_line if index == 4 else f"Reply {index}",
        "at": datetime(2026, 8, 20, 4, index, tzinfo=timezone.utc),
    } for index in range(5)])
    view = console.build_ticket_detail(
        ticket, action_id="j" * 32, flags=[], history=[],
    )
    text = "\n".join(str(node["content"]) for node in _nodes(view) if "content" in node)
    trimmed = "x" * 119 + "…"
    assert trimmed in text
    assert "x" * 120 not in text
    assert "Reply 0" not in text
    assert "Reply 1" not in text
    assert "Reply 2" in text
    assert "Reply 3" in text
    # Newest (index 4, the trimmed long line) first, then 3, then 2.
    assert text.index(trimmed) < text.index("Reply 3") < text.index("Reply 2")
    _assert_component_limits(view)


def test_transcript_uppercases_a_tag_looking_token_in_a_raw_answer():
    """A tag-shaped token the applicant typed (e.g. lowercase, letter-O)
    renders normalized for staff, without changing what is stored."""
    tag_ticket = _ticket(16, answers=[{
        "message_id": 700,
        "kind": "answer",
        "content": "My tag is #9llUR8, thanks!",
        "at": datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc),
    }])
    view = console.build_ticket_detail(
        tag_ticket, action_id="f" * 32, flags=[], history=[],
    )
    text = "\n".join(str(node["content"]) for node in _nodes(view) if "content" in node)
    assert "#9LLUR8" in text
    assert "#9llUR8" not in text
    # The stored answer itself is untouched.
    assert tag_ticket["answers"][0]["content"] == "My tag is #9llUR8, thanks!"


def test_ticket_label_mentions_in_real_text_but_not_in_a_select_label():
    """Discord select-option labels cannot render a mention, so that path
    keeps the stored display name; every other caller gets a mention."""
    ticket = _ticket(17, username="Some Applicant")
    real_text = console._ticket_label(ticket, username=True)
    assert f"<@{ticket['user_id']}>" in real_text
    assert "Some Applicant" not in real_text

    select_label = console._ticket_label(ticket, username=True, markdown=False)
    assert "Some Applicant" in select_label
    assert "<@" not in select_label


def test_shared_hub_actions_are_no_return_so_dispatcher_cannot_edit_the_root():
    pick = dispatcher.registered_functions["ticket_v2_console_pick"]
    find = dispatcher.registered_functions["ticket_v2_console_find"]
    assert pick.no_return is True
    assert find.no_return is True
    assert find.opens_modal is True
    assert find.preload_state is False
    assert dispatcher.registered_functions["ticket_v2_console_view"].requires_state is True
    again = dispatcher.registered_functions["ticket_v2_console_search_again"]
    assert again.opens_modal is True
    assert again.no_return is True
    assert again.preload_state is False
    deny = dispatcher.registered_functions["ticket_v2_console_deny"]
    assert deny.opens_modal is True
    assert deny.no_return is True
    assert deny.preload_state is False
    root_submit = dispatcher.registered_functions["ticket_v2_console_find_root_submit"]
    assert root_submit.is_modal is True
    assert root_submit.preload_state is False


def test_dispatcher_never_preloads_ticket_modal_openers(monkeypatch):
    modals = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

        def __init__(self, custom_id):
            self.interaction = SimpleNamespace(custom_id=custom_id)

        async def defer(self, **_kwargs):
            raise AssertionError("a modal opener was deferred")

        async def respond_with_modal(self, **kwargs):
            modals.append(kwargs["custom_id"])

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("dispatcher preloaded state before a ticket modal")

    monkeypatch.setattr(dispatcher, "get_state", forbidden)

    for custom_id in (
        "ticket_v2_console_find:hub",
        "ticket_v2_console_search_again:search",
        "ticket_v2_console_deny:detail",
    ):
        asyncio.run(dispatcher._dispatch(Context(custom_id), object()))

    assert modals == [
        "ticket_v2_console_find_root_submit:33",
        "ticket_v2_console_find_submit:search",
        "ticket_v2_console_deny_submit:detail",
    ]


def test_ticket_search_and_deny_openers_send_modals_without_prerequisite_work(
    monkeypatch,
):
    calls = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

        async def respond_with_modal(self, **kwargs):
            calls.append(kwargs["custom_id"])

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a modal opener performed prerequisite work")

    monkeypatch.setattr(console, "get_state", forbidden)
    monkeypatch.setattr(console.perms, "is_recruiter", forbidden)
    monkeypatch.setattr(console, "_create_search_state", forbidden)

    ctx = Context()
    asyncio.run(console.ticket_console_find(ctx, "hub", mongo=object()))
    asyncio.run(console.ticket_console_search_again(ctx, "search", mongo=object()))
    asyncio.run(console.ticket_console_deny(ctx, "detail", mongo=object()))
    asyncio.run(console.FindCommand.invoke._func(
        SimpleNamespace(query=None), ctx, mongo=object(),
    ))

    assert calls == [
        "ticket_v2_console_find_root_submit:33",
        "ticket_v2_console_find_submit:search",
        "ticket_v2_console_deny_submit:detail",
        "ticket_v2_console_find_root_submit:33",
    ]


def test_public_picker_creates_ephemeral_followup_and_leaves_hub_byte_exact(monkeypatch):
    public_message = {
        "id": "shared-hub",
        "components": [{"type": "chart"}, {"type": "picker"}, {"type": "find"}],
    }
    before = json.dumps(copy.deepcopy(public_message), sort_keys=True).encode()
    followups = []

    class Interaction:
        values = ("ticket_1001",)
        message = public_message

        async def execute(self, **kwargs):
            followups.append(kwargs)

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

        async def respond(self, *_args, **_kwargs):
            raise AssertionError("a deferred public-hub click must not call respond")

    async def allowed(_member, _mongo):
        return True

    async def find_one(_mongo, _query):
        return _ticket(1)

    async def detail(_mongo, _ticket_doc, **_kwargs):
        return ["PRIVATE"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console.store, "find_one", find_one)
    monkeypatch.setattr(console, "_ticket_detail_panel", detail)

    asyncio.run(console.ticket_console_pick(Context(), "hub", mongo=object()))

    after = json.dumps(public_message, sort_keys=True).encode()
    assert after == before
    assert len(followups) == 1
    assert followups[0]["components"] == ["PRIVATE"]
    assert followups[0]["flags"] & hikari.MessageFlag.EPHEMERAL
    assert followups[0]["flags"] & hikari.MessageFlag.IS_COMPONENTS_V2


def test_search_again_submit_defers_before_permission_and_mongo_work(monkeypatch):
    events = []

    class Interaction:
        components = [[SimpleNamespace(custom_id="query", value="Applicant")]]

        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

        async def respond(self, *_args, **_kwargs):
            raise AssertionError("a valid search must fulfill its deferred response")

    async def allowed(_member, _mongo):
        events.append(("permission", {}))
        return True

    async def get(_mongo, _action_id, _projection):
        assert _projection == {
            "type": 1,
            "owner_id": 1,
            "guild_id": 1,
        }
        events.append(("state-load", {}))
        return {
            "type": "ticket_v2_console_search",
            "owner_id": 22,
            "guild_id": 33,
        }

    async def state(_mongo, **kwargs):
        events.append(("state", {}))
        assert kwargs == {"owner_id": 22, "guild_id": 33, "query": "Applicant"}
        return "next-search"

    async def render(_mongo, **_kwargs):
        events.append(("render", {}))
        assert _kwargs["action_id"] == "next-search"
        return ["RESULT"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console, "_create_search_state", state)
    monkeypatch.setattr(console, "_render_search_session", render)

    asyncio.run(console.ticket_console_find_submit(Context(), "search", mongo=object()))

    assert events[0] == ("defer", {"ephemeral": True})
    assert [event[0] for event in events] == [
        "defer", "state-load", "permission", "state", "render", "edit",
    ]
    assert events[-1][1]["components"] == ["RESULT"]


def test_root_find_submit_acknowledges_before_creating_owner_bound_state(monkeypatch):
    events = []

    class Interaction:
        components = [[SimpleNamespace(custom_id="query", value="Applicant")]]

        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def allowed(_member, _mongo):
        events.append(("permission", {}))
        return True

    async def state(_mongo, **kwargs):
        events.append(("state", kwargs))
        return "root-search"

    async def render(_mongo, **kwargs):
        events.append(("render", kwargs))
        return ["RESULT"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "_create_search_state", state)
    monkeypatch.setattr(console, "_render_search_session", render)

    asyncio.run(console.ticket_console_find_root_submit(
        Context(), "33", mongo=object(),
    ))

    assert [event[0] for event in events] == [
        "defer", "permission", "state", "render", "edit",
    ]
    assert events[2][1] == {
        "owner_id": 22,
        "guild_id": 33,
        "query": "Applicant",
    }
    assert events[3][1]["action_id"] == "root-search"


def test_status_filter_re_renders_the_panel_instead_of_blanking_it_when_not_recruiter(
    monkeypatch,
):
    """The dispatcher already deferred this interaction as a message edit
    (extensions/components.py). Returning None from the recruiter-check
    branch would edit the panel down to zero components, blanking a search
    panel that still legitimately belongs to its owner."""
    responses = []

    class Context:
        user = SimpleNamespace(id=22)
        member = object()

        async def respond(self, *args, **kwargs):
            responses.append((args, kwargs))

    async def denied(_member, _mongo):
        return False

    async def render(_mongo, **kwargs):
        assert kwargs == {
            "action_id": "abc",
            "owner_id": 22,
            "guild_id": 33,
            "query": "Applicant",
            "statuses": ["open"],
            "ticket_types": [],
        }
        return ["UNCHANGED PANEL"]

    monkeypatch.setattr(console.perms, "is_recruiter", denied)
    monkeypatch.setattr(console, "_render_search_session", render)

    result = asyncio.run(console.ticket_console_status(
        Context(), "abc",
        owner_id=22, guild_id=33, query="Applicant",
        statuses=["open"], ticket_types=[],
        mongo=object(),
    ))

    assert result == ["UNCHANGED PANEL"]
    assert len(responses) == 1
    assert "Only recruiters" in responses[0][0][0]


def test_console_deny_submit_defers_then_rejects_wrong_guild_before_transition(
    monkeypatch,
):
    events = []

    class Interaction:
        message = None
        components = [[SimpleNamespace(custom_id="reason", value="Clear reason")]]

        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22, username="Recruiter")
        member = object()
        guild_id = 33

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def get(_mongo, _action_id, _projection):
        events.append(("state", {}))
        return {
            "type": "ticket_v2_console_detail",
            "owner_id": 22,
            "guild_id": 44,
            "ticket_id": "ticket_1",
        }

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("wrong-guild submission reached the transition")

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console.resolve, "deny_ticket", forbidden)

    asyncio.run(console.ticket_console_deny_submit(
        Context(), "detail", mongo=object(), bot=object(),
    ))

    assert [event[0] for event in events] == ["defer", "state", "edit"]


def test_console_deny_submit_authorizes_before_loading_private_state(monkeypatch):
    events = []
    private = {
        "type": "ticket_v2_console_detail",
        "owner_id": 22,
        "guild_id": 33,
        "ticket_id": "ticket_1",
        "expected_status": "open",
        "expected_rev": 4,
    }

    class Interaction:
        message = None
        components = [[SimpleNamespace(custom_id="reason", value="Clear reason")]]

        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22, username="Recruiter")
        member = object()
        guild_id = 33

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

    async def get(_mongo, _action_id, projection=None):
        if projection is not None:
            assert projection == {
                "type": 1,
                "owner_id": 1,
                "guild_id": 1,
            }
            events.append(("envelope", {}))
            return {
                "type": private["type"],
                "owner_id": private["owner_id"],
                "guild_id": private["guild_id"],
            }
        events.append(("private-state", {}))
        return dict(private)

    async def allowed(_member, _mongo):
        events.append(("permission", {}))
        return True

    async def deny(*_args, **_kwargs):
        events.append(("transition", {}))
        return console.store.Transition(console.store.MISSING, None)

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console.resolve, "deny_ticket", deny)

    asyncio.run(console.ticket_console_deny_submit(
        Context(), "detail", mongo=object(), bot=object(),
    ))

    # The extra "edit" before "transition" is the in-progress notice shown
    # right before the (potentially slow) deny_ticket call; the final "edit"
    # delivers the actual result.
    assert [event[0] for event in events] == [
        "defer", "envelope", "permission", "private-state", "edit", "transition", "edit",
    ]


def test_console_deny_submit_already_decided_mentions_and_suppresses_pings(monkeypatch):
    """The already-decided notice must mention the decider, never their
    stored name, and the edit delivering it must suppress notifications."""
    private = {
        "type": "ticket_v2_console_detail",
        "owner_id": 22,
        "guild_id": 33,
        "ticket_id": "ticket_1",
        "expected_status": "open",
    }
    ticket = _ticket(
        23,
        status="approved",
        approved_by=777,
        approved_by_name="Someone Else",
        approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    edits = []

    class Interaction:
        message = None
        components = [[SimpleNamespace(custom_id="reason", value="Clear reason")]]

        async def edit_initial_response(self, **kwargs):
            edits.append(kwargs)

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22, username="Recruiter")
        member = object()
        guild_id = 33

        async def defer(self, **kwargs):
            return None

    async def get(_mongo, _action_id, projection=None):
        if projection is not None:
            return {
                "type": private["type"],
                "owner_id": private["owner_id"],
                "guild_id": private["guild_id"],
            }
        return dict(private)

    async def allowed(_member, _mongo):
        return True

    async def deny(*_args, **_kwargs):
        return console.store.Transition(console.store.LOST, ticket)

    async def insert(_mongo, _document):
        return None

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console, "insert_state", insert)
    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console.resolve, "deny_ticket", deny)

    asyncio.run(console.ticket_console_deny_submit(
        Context(), "detail", mongo=object(), bot=object(),
    ))

    # The first edit is the in-progress notice shown before deny_ticket
    # runs; the last edit delivers the actual already-decided result.
    assert len(edits) == 2
    kwargs = edits[-1]
    content = "\n".join(
        str(node["content"]) for node in _nodes(kwargs["components"]) if "content" in node
    )
    assert "<@777>" in content
    assert "Someone Else" not in content
    assert kwargs["user_mentions"] is False
    assert kwargs["role_mentions"] is False
    assert kwargs["mentions_everyone"] is False


def test_console_approve_opens_a_confirm_step_before_touching_anything(monkeypatch):
    """Commit 2: Approve is one click plus a confirm, never a silent single click."""
    ticket = _ticket(21, status="open", username="Some Applicant", ticket_type="fwa")

    async def find(_mongo, query):
        assert query["_id"] == ticket["_id"]
        return copy.deepcopy(ticket)

    monkeypatch.setattr(console.store, "find_one", find)

    ctx = SimpleNamespace(user=SimpleNamespace(id=22, username="Recruiter"))

    view = asyncio.run(console.ticket_console_approve(
        ctx, "detail", owner_id=22, guild_id=ticket["guild_id"],
        ticket_id=ticket["_id"], mongo=object(),
    ))
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    labels = [str(node["label"]) for node in _nodes(view) if "label" in node]
    # A mention of the applicant, never the stored username.
    assert f"<@{ticket['user_id']}>" in content
    assert "Some Applicant" not in content
    assert "FWA" in content
    assert labels == ["Approve", "Cancel"]
    custom_ids = [str(node["custom_id"]) for node in _nodes(view) if "custom_id" in node]
    assert custom_ids == [
        "ticket_v2_console_approve_go:detail",
        "ticket_v2_console_confirm_cancel:detail",
    ]
    _assert_component_limits(view)


def test_console_approve_confirm_step_completes_the_approval(monkeypatch):
    """The first click only renders a confirm panel (no Mongo write yet).
    Clicking that panel's own Approve button -- ticket_v2_console_approve_go,
    wired with the exact same action_id -- must then perform the real
    approval and refresh the hub. No test previously went through both
    steps of ticket_console_approve's confirm gate."""
    ticket = _ticket(21, status="open", username="Some Applicant", ticket_type="fwa")

    async def find(_mongo, query):
        assert query["_id"] == ticket["_id"]
        return copy.deepcopy(ticket)

    monkeypatch.setattr(console.store, "find_one", find)

    ctx = SimpleNamespace(
        user=SimpleNamespace(id=22, username="Recruiter"),
        member=SimpleNamespace(id=22),
    )

    view = asyncio.run(console.ticket_console_approve(
        ctx, "detail", owner_id=22, guild_id=ticket["guild_id"],
        ticket_id=ticket["_id"], mongo=object(),
    ))
    custom_ids = [str(node["custom_id"]) for node in _nodes(view) if "custom_id" in node]
    approve_go_id, cancel_id = custom_ids
    assert approve_go_id == "ticket_v2_console_approve_go:detail"
    assert cancel_id == "ticket_v2_console_confirm_cancel:detail"

    approve_calls = {}

    async def approve(*_args, **kwargs):
        approve_calls.update(kwargs)
        return console.store.Transition(console.store.WON, ticket)

    refresh_calls = []

    async def refresh(*_args, reason, **_kwargs):
        refresh_calls.append(reason)
        return True

    monkeypatch.setattr(console.resolve, "approve_ticket", approve)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    # Follow the confirm panel's own custom_id, not a hardcoded one.
    action_id = approve_go_id.split(":", 1)[1]
    go_view = asyncio.run(console.ticket_console_approve_go(
        ctx, action_id, owner_id=22, guild_id=ticket["guild_id"],
        ticket_id=ticket["_id"], mongo=object(), bot=object(),
    ))

    assert approve_calls["ticket_id"] == ticket["_id"]
    assert refresh_calls == ["ticket approved"]
    content = "\n".join(
        str(node["content"]) for node in _nodes(go_view) if "content" in node
    )
    assert "Ticket approved" in content
    _assert_component_limits(go_view)


def test_console_approve_go_shows_in_progress_notice_before_calling_approve_ticket(
    monkeypatch,
):
    """Owner decision, live smoke test: the confirm buttons stayed live and
    unchanged while resolve.approve_ticket ran (seconds to tens of seconds),
    because the dispatcher's own defer(edit=True) draws no loading state --
    inviting a second click that loses the CAS. The handler must show its
    own buttonless in-progress card before calling approve_ticket, not
    after."""
    ticket = _ticket(21, status="open")
    events = []

    class Interaction:
        async def edit_initial_response(self, **kwargs):
            events.append(("in_progress", kwargs))

    ctx = SimpleNamespace(
        user=SimpleNamespace(id=22, username="Recruiter"),
        member=SimpleNamespace(id=22),
        interaction=Interaction(),
    )

    async def approve(*_args, **_kwargs):
        events.append(("approve_ticket", {}))
        return console.store.Transition(console.store.WON, ticket)

    async def refresh(*_args, **_kwargs):
        return True

    monkeypatch.setattr(console.resolve, "approve_ticket", approve)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    asyncio.run(console.ticket_console_approve_go(
        ctx, "detail", owner_id=22, guild_id=ticket["guild_id"],
        ticket_id=ticket["_id"], mongo=object(), bot=object(),
    ))

    assert [event[0] for event in events] == ["in_progress", "approve_ticket"]
    heading = "\n".join(
        str(node["content"])
        for node in _nodes(events[0][1]["components"])
        if "content" in node
    )
    assert "Approving" in heading
    assert events[0][1]["user_mentions"] is False
    assert events[0][1]["role_mentions"] is False
    assert events[0][1]["mentions_everyone"] is False


def test_console_deny_submit_shows_in_progress_notice_before_calling_deny_ticket(
    monkeypatch,
):
    """Mirrors the approve-go ordering test above for the deny-modal path:
    the in-progress notice must be shown before resolve.deny_ticket runs."""
    private = {
        "type": "ticket_v2_console_detail",
        "owner_id": 22,
        "guild_id": 33,
        "ticket_id": "ticket_1",
        "expected_status": "open",
    }
    ticket = _ticket(21, status="denied")
    events = []

    class Interaction:
        message = None
        components = [[SimpleNamespace(custom_id="reason", value="Clear reason")]]

        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22, username="Recruiter")
        member = object()
        guild_id = 33

        async def defer(self, **kwargs):
            return None

    async def get(_mongo, _action_id, projection=None):
        if projection is not None:
            return {
                "type": private["type"],
                "owner_id": private["owner_id"],
                "guild_id": private["guild_id"],
            }
        return dict(private)

    async def allowed(_member, _mongo):
        return True

    async def deny(*_args, **_kwargs):
        events.append(("deny_ticket", {}))
        return console.store.Transition(console.store.WON, ticket)

    async def refresh(*_args, **_kwargs):
        return True

    monkeypatch.setattr(console, "get_state", get)
    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console.resolve, "deny_ticket", deny)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    asyncio.run(console.ticket_console_deny_submit(
        Context(), "detail", mongo=object(), bot=object(),
    ))

    # The in-progress notice ("edit") is delivered before deny_ticket runs;
    # the trailing "edit" delivers the actual result.
    assert [event[0] for event in events] == ["edit", "deny_ticket", "edit"]
    heading = "\n".join(
        str(node["content"])
        for node in _nodes(events[0][1]["components"])
        if "content" in node
    )
    assert "Denying" in heading


def test_console_approve_go_returns_a_red_notice_when_approve_ticket_raises(monkeypatch):
    """Refuter fix: `ticket_console_approve_go` called `_show_in_progress`
    then `resolve.approve_ticket` with no try/except, so an exception left
    the recruiter staring at a buttonless "Approving..." panel forever --
    the handler never returned anything for the dispatcher to render. It
    must now catch the exception (after the in-progress edit already ran)
    and return the same red "Decision not saved" notice used elsewhere."""
    ticket = _ticket(21, status="open")
    events = []

    class Interaction:
        async def edit_initial_response(self, **kwargs):
            events.append(("in_progress", kwargs))

    ctx = SimpleNamespace(
        user=SimpleNamespace(id=22, username="Recruiter"),
        member=SimpleNamespace(id=22),
        interaction=Interaction(),
    )

    async def approve(*_args, **_kwargs):
        raise RuntimeError("mongo write timed out")

    async def refresh(*_args, **_kwargs):
        raise AssertionError("a raised approve_ticket must not request a hub refresh")

    monkeypatch.setattr(console.resolve, "approve_ticket", approve)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    view = asyncio.run(console.ticket_console_approve_go(
        ctx, "detail", owner_id=22, guild_id=ticket["guild_id"],
        ticket_id=ticket["_id"], mongo=object(), bot=object(),
    ))

    # The in-progress edit ran before the exception -- there is no second
    # panel state from the (never reached) success path.
    assert [event[0] for event in events] == ["in_progress"]
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Decision not saved" in content
    assert view[0].accent_color == console.ACCENT_RED
    _assert_component_limits(view)


def test_console_approve_go_no_longer_sends_a_rev_and_shows_already_approved_on_lost(
    monkeypatch,
):
    """Commit 1: the console drops the client-side expected_rev CAS entirely,
    and the only conflict check left is 'someone else already decided this'."""
    ticket = _ticket(
        21,
        status="approved",
        approved_by=888,
        approved_by_name="Other Recruiter",
        approved_at=datetime(2026, 9, 1, tzinfo=timezone.utc),
    )
    calls = {}

    async def approve(*_args, **kwargs):
        calls.update(kwargs)
        return console.store.Transition(console.store.LOST, ticket)

    async def insert(_mongo, document):
        calls["saved_state"] = document

    async def refresh(*_args, **_kwargs):
        raise AssertionError("a LOST outcome must not request a hub refresh")

    monkeypatch.setattr(console.resolve, "approve_ticket", approve)
    monkeypatch.setattr(console, "insert_state", insert)
    monkeypatch.setattr(console, "request_hub_refresh_best_effort", refresh)

    ctx = SimpleNamespace(
        user=SimpleNamespace(id=22, username="Recruiter"),
        member=SimpleNamespace(id=22),
    )
    view = asyncio.run(console.ticket_console_approve_go(
        ctx, "detail", owner_id=22, guild_id=ticket["guild_id"],
        ticket_id=ticket["_id"], mongo=object(), bot=object(),
    ))

    assert "expected_rev" not in calls
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Already approved" in content
    assert "<@888>" in content
    assert "Other Recruiter" not in content


def test_direct_find_command_defers_before_permission_and_search_work(monkeypatch):
    events = []

    class Interaction:
        async def edit_initial_response(self, **kwargs):
            events.append(("edit", kwargs))

    class Context:
        interaction = Interaction()
        user = SimpleNamespace(id=22)
        member = object()
        guild_id = 33

        async def defer(self, **kwargs):
            events.append(("defer", kwargs))

        async def respond(self, *_args, **_kwargs):
            raise AssertionError("a direct search must fulfill its deferred response")

    async def allowed(_member, _mongo):
        events.append(("permission", {}))
        return True

    async def state(_mongo, **_kwargs):
        events.append(("state", {}))
        return "search"

    async def render(_mongo, **_kwargs):
        events.append(("render", {}))
        return ["RESULT"]

    monkeypatch.setattr(console.perms, "is_recruiter", allowed)
    monkeypatch.setattr(console, "_create_search_state", state)
    monkeypatch.setattr(console, "_render_search_session", render)

    asyncio.run(console.FindCommand.invoke._func(
        SimpleNamespace(query="Applicant"), Context(), mongo=object(),
    ))

    assert [event[0] for event in events] == [
        "defer", "permission", "state", "render", "edit",
    ]


def test_refresh_scheduler_coalesces_concurrent_requests(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()
    calls = []

    async def drain(_bot, _mongo, *, debounce):
        calls.append(debounce)
        started.set()
        await release.wait()
        return True

    monkeypatch.setattr(console, "_drain_hub_refreshes", drain)
    console._refresh_tasks.clear()

    async def run():
        bot = object()
        mongo = object()
        first = console._schedule_hub_refresh(bot, mongo)
        await started.wait()
        second = console._schedule_hub_refresh(bot, mongo)
        assert first is second
        release.set()
        await first

    asyncio.run(run())
    assert calls == [True]


def test_refresh_worker_recovers_after_outage_without_another_ticket_event(monkeypatch):
    attempts = []

    async def drain(_bot, _mongo, *, debounce):
        attempts.append(debounce)
        return len(attempts) >= 2

    async def dirty(_mongo):
        return {"channel_id": 1, "desired_revision": 2, "applied_revision": 1}

    async def no_delay(_seconds):
        return None

    monkeypatch.setattr(console, "_drain_hub_refreshes", drain)
    monkeypatch.setattr(console, "_hub_state", dirty)
    monkeypatch.setattr(console.asyncio, "sleep", no_delay)
    console._refresh_tasks.clear()

    async def run():
        await console._schedule_hub_refresh(object(), object())

    asyncio.run(run())
    assert attempts == [True, False]


def test_refresh_worker_backs_off_exponentially_then_caps_at_one_hour(monkeypatch):
    """A permanent console-config failure (channel gone, privacy validation)
    must not keep reconciling at a fixed ~77s cadence forever: each
    unsuccessful cycle should double the wait starting at 60s, capped at
    3600s (1h)."""
    delays = []

    async def drain(_bot, _mongo, *, debounce):
        # Succeed once eight backoff sleeps have been observed, so the
        # doubling sequence and the cap are both visible.
        return len(delays) >= 8

    async def dirty(_mongo):
        return {"channel_id": 1, "desired_revision": 2, "applied_revision": 1}

    async def record_sleep(seconds):
        delays.append(seconds)

    monkeypatch.setattr(console, "_drain_hub_refreshes", drain)
    monkeypatch.setattr(console, "_hub_state", dirty)
    monkeypatch.setattr(console.asyncio, "sleep", record_sleep)

    result = asyncio.run(
        console._hub_refresh_worker(object(), object(), debounce=False)
    )

    assert result is True
    assert delays == [60.0, 120.0, 240.0, 480.0, 960.0, 1920.0, 3600.0, 3600.0]


def test_worker_giving_up_on_missing_config_clears_stale_refresh_error():
    """A prior publish failure recorded `refresh_error`/`refresh_failures` on
    the shared hub state. If the console channel is then cleared, the
    refresh worker gives up immediately (there is nowhere left to publish)
    -- it must not leave that stale error sitting there forever, or
    `/tickets rollout-status` keeps reporting a failure that stopped being
    true the moment the channel was unset."""

    class Collection:
        def __init__(self, document):
            self.document = document

        async def find_one(self, _query):
            return copy.deepcopy(self.document)

        async def find_one_and_update(self, _query, update, **_kwargs):
            self._apply(update)
            return copy.deepcopy(self.document)

        async def update_one(self, _query, update, **_kwargs):
            self._apply(update)

        def _apply(self, update):
            for key, value in update.get("$set", {}).items():
                self.document[key] = value
            for key in update.get("$unset", {}):
                self.document.pop(key, None)
            for key, value in update.get("$inc", {}).items():
                self.document[key] = self.document.get(key, 0) + value
            for key, value in update.get("$max", {}).items():
                self.document[key] = max(self.document.get(key, value), value)

    document = {
        "_id": console.HUB_STATE_ID,
        "desired_revision": 3,
        "applied_revision": 2,
        "channel_id": None,
        "refresh_error": "RuntimeError: ticket console channel is not configured",
        "refresh_failures": 4,
    }
    collection = Collection(document)
    mongo = SimpleNamespace(ticket_setup=collection)

    result = asyncio.run(console._drain_hub_refreshes(
        SimpleNamespace(), mongo, debounce=False
    ))

    assert result is False
    assert collection.document.get("refresh_error") is None
    assert collection.document.get("refresh_failures") == 0
    assert asyncio.run(console.refresh_status(mongo)) == "not configured"


def test_staff_context_delivery_is_one_durable_message_and_updates_in_place(monkeypatch):
    class Collection:
        def __init__(self):
            self.document = None

        async def update_one(self, query, update, **kwargs):
            if self.document is None:
                self.document = {"_id": query["_id"]}
                self.document.update(update.get("$setOnInsert", {}))
            self.document.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                self.document.pop(key, None)
            return SimpleNamespace(matched_count=1)

        async def find_one_and_update(self, _query, update, **_kwargs):
            self.document.update(update.get("$set", {}))
            return dict(self.document)

        async def find_one(self, _query):
            return dict(self.document or {})

    class Rest:
        def __init__(self):
            self.creates = 0
            self.edits = 0

        async def create_message(self, **_kwargs):
            self.creates += 1
            return SimpleNamespace(id=900)

        async def edit_message(self, **_kwargs):
            self.edits += 1

    body = {"text": "first"}

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", body["text"])

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    collection = Collection()
    mongo = SimpleNamespace(ticket_automation_state=collection)
    rest = Rest()
    bot = SimpleNamespace(rest=rest)
    ticket = _ticket(15)

    async def run():
        first = await console.deliver_staff_identity_context(bot, mongo, ticket)
        second = await console.deliver_staff_identity_context(bot, mongo, ticket)
        body["text"] = "tag match added"
        third = await console.deliver_staff_identity_context(bot, mongo, ticket)
        return first, second, third

    assert asyncio.run(run()) == (900, 900, 900)
    assert (rest.creates, rest.edits) == (1, 1)
    assert collection.document["_id"] == "ticket_staff_context:ticket_1015"
    assert collection.document["message_id"] == 900


def test_staff_context_queue_is_idempotent_and_refreshes_one_bound_row():
    ticket = _ticket(16, venue="thread")
    states = _ContextRecoveryStates([])
    mongo = SimpleNamespace(ticket_automation_state=states)

    async def run():
        first = await console.queue_staff_identity_context(mongo, ticket)
        second = await console.queue_staff_identity_context(
            mongo, ticket, open_only_refresh=True
        )
        return first, second

    state_id = f"ticket_staff_context:{ticket['_id']}"
    assert asyncio.run(run()) == (state_id, state_id)
    assert set(states.documents) == {state_id}
    state = states.documents[state_id]
    assert state["ticket_id"] == ticket["_id"]
    assert state["staff_space_id"] == ticket["location"]["staff_space_id"]
    assert state["delivery_state"] == "pending"
    assert state["open_only_refresh"] is True
    assert state["refresh_generation"] == 2


def test_staff_context_reuses_committed_message_after_checkpoint_loss(monkeypatch):
    class Collection:
        def __init__(self):
            self.document = None
            self.fail_message_checkpoint = True

        async def update_one(self, query, update, **_kwargs):
            if self.document is None:
                self.document = {"_id": query["_id"]}
                self.document.update(update.get("$setOnInsert", {}))
            if self.fail_message_checkpoint and "message_id" in update.get("$set", {}):
                self.fail_message_checkpoint = False
                raise TimeoutError("checkpoint unavailable after Discord committed")
            self.document.update(update.get("$set", {}))
            for key in update.get("$unset", {}):
                self.document.pop(key, None)
            return SimpleNamespace(matched_count=1)

        async def find_one_and_update(self, _query, update, **_kwargs):
            self.document.update(update.get("$set", {}))
            return dict(self.document)

        async def find_one(self, _query):
            return dict(self.document or {})

    class Messages:
        def __init__(self, messages):
            self.messages = messages

        def limit(self, amount):
            return Messages(self.messages[:amount])

        async def to_list(self):
            return list(self.messages)

    class Rest:
        def __init__(self):
            self.creates = 0
            self.edits = 0
            self.messages = []

        def fetch_messages(self, _channel_id):
            return Messages(self.messages)

        async def create_message(self, **kwargs):
            self.creates += 1
            message = SimpleNamespace(
                id=900,
                author=SimpleNamespace(id=7),
                components=kwargs["components"],
            )
            self.messages.append(message)
            return message

        async def edit_message(self, **_kwargs):
            self.edits += 1

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", "Matched history")

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    collection = Collection()
    rest = Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=collection)

    async def run():
        first = await console.deliver_staff_identity_context(bot, mongo, _ticket(17))
        rest.messages[:0] = [
            SimpleNamespace(
                id=2000 + index,
                author=SimpleNamespace(id=7),
                components=[],
            )
            for index in range(150)
        ]
        second = await console.deliver_staff_identity_context(bot, mongo, _ticket(17))
        return first, second

    assert asyncio.run(run()) == (None, 900)
    assert (rest.creates, rest.edits) == (1, 1)
    assert collection.document["message_id"] == 900


def test_fwa_chocolate_recheck_skips_the_scan_once_fully_checkpointed(monkeypatch):
    class Collection:
        def __init__(self):
            self.document = None

        async def update_one(self, query, update, **_kwargs):
            if self.document is None:
                self.document = {"_id": query["_id"]}
                self.document.update(update.get("$setOnInsert", {}))
            self.document.update(update.get("$set", {}))
            return SimpleNamespace(matched_count=1)

        async def find_one_and_update(self, _query, update, **_kwargs):
            self.document.update(update.get("$set", {}))
            return dict(self.document)

        async def find_one(self, _query):
            return dict(self.document or {})

    limit_calls: list[int] = []

    class Messages:
        def __init__(self, messages):
            self.messages = messages

        def limit(self, amount):
            limit_calls.append(amount)
            return Messages(self.messages[:amount])

        async def to_list(self):
            return list(self.messages)

    class Rest:
        def __init__(self):
            self.creates = 0
            self.edits = 0
            self.messages = []
            self.fetch_calls: list[int] = []

        def fetch_messages(self, channel_id):
            self.fetch_calls.append(channel_id)
            return Messages(self.messages)

        async def create_message(self, **kwargs):
            self.creates += 1
            message = SimpleNamespace(
                id=900 + self.creates,
                author=SimpleNamespace(id=7),
                components=kwargs["components"],
            )
            self.messages.append(message)
            return message

        async def edit_message(self, **_kwargs):
            self.edits += 1

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", "Matched history")

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    collection = Collection()
    rest = Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))
    mongo = SimpleNamespace(ticket_automation_state=collection)

    ticket_doc = _ticket(21, linked_accounts={
        "state": "ready",
        "current": [{"tag": "#ABC123", "name": "Alt One"}],
        "current_tags": ["#ABC123"],
        "revision": 1,
    })

    async def run():
        await console.deliver_staff_identity_context(bot, mongo, ticket_doc)
        fetches_after_first = len(rest.fetch_calls)

        await console.deliver_staff_identity_context(bot, mongo, ticket_doc)
        fetches_after_second = len(rest.fetch_calls)

        # Simulate the checkpoint losing a chocolate message id.
        collection.document["chocolate_message_ids"] = []
        await console.deliver_staff_identity_context(bot, mongo, ticket_doc)
        fetches_after_third = len(rest.fetch_calls)

        return fetches_after_first, fetches_after_second, fetches_after_third

    fetches_after_first, fetches_after_second, fetches_after_third = asyncio.run(run())

    # Second call: main context and the chocolate page are both already
    # checkpointed, so the staff thread is never re-read.
    assert fetches_after_second == fetches_after_first
    # Third call: the chocolate checkpoint is missing, so exactly one bounded
    # fetch happens to recover it.
    assert fetches_after_third == fetches_after_second + 1
    assert limit_calls[-1] == 100


def test_failed_staff_context_recovers_once_and_is_not_selected_again(monkeypatch):
    ticket = _ticket(21, venue="thread")
    state_id = f"ticket_staff_context:{ticket['_id']}"
    states = _ContextRecoveryStates([{
        "_id": state_id,
        "kind": "ticket_staff_context",
        "ticket_id": ticket["_id"],
        "staff_space_id": ticket["location"]["staff_space_id"],
        "delivery_state": "failed",
        "delivery_error": "TimeoutError",
        "created_at": ticket["created_at"],
    }])

    class Messages:
        async def to_list(self):
            return []

    class Rest:
        def __init__(self):
            self.creates = 0

        def fetch_messages(self, _channel_id):
            return Messages()

        async def create_message(self, **_kwargs):
            self.creates += 1
            return SimpleNamespace(id=900)

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", "Matched flag")

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    rest = Rest()
    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_ContextRecoveryTickets([ticket]),
    )
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))

    first = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=bot, mongo=mongo, limit=25
    ))
    second = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=bot, mongo=mongo, limit=25
    ))

    assert first == {"processed": 1, "completed": 1, "failed": 0}
    assert second == {"processed": 0, "completed": 0, "failed": 0}
    assert rest.creates == 1
    assert states.documents[state_id]["delivery_state"] == "delivered"
    assert states.documents[state_id]["delivery_error"] is None


def test_open_staff_context_sweep_closes_missing_state_gap_across_batches(monkeypatch):
    tickets = [_ticket(number, venue="thread") for number in range(40, 45)]
    states = _ContextRecoveryStates([])

    class Messages:
        async def to_list(self):
            return []

    class Rest:
        def __init__(self):
            self.created_channels = []

        def fetch_messages(self, _channel_id):
            return Messages()

        async def create_message(self, **kwargs):
            self.created_channels.append(kwargs["channel"])
            return SimpleNamespace(id=900 + len(self.created_channels))

        async def edit_message(self, **_kwargs):
            raise AssertionError("a missing context must create, not edit")

    async def context(_mongo, ticket_doc):
        return console._notice("Applicant context", ticket_doc["_id"])

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    rest = Rest()
    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_OpenContextSweepTickets(tickets),
    )
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))

    async def run():
        after = None
        batches = []
        while True:
            result = await console.recover_open_staff_identity_contexts(
                bot=bot,
                mongo=mongo,
                after_ticket_id=after,
                limit=2,
            )
            batches.append(result)
            after = result["after_ticket_id"]
            if result["exhausted"]:
                return batches

    batches = asyncio.run(run())

    assert [item["processed"] for item in batches] == [2, 2, 1]
    assert [item["failed"] for item in batches] == [0, 0, 0]
    assert rest.created_channels == [
        ticket["location"]["staff_space_id"] for ticket in tickets
    ]
    for ticket in tickets:
        state = states.documents[f"ticket_staff_context:{ticket['_id']}"]
        assert state["delivery_state"] == "delivered"
        assert state["delivery_attempts"] == 1


def test_open_staff_context_sweep_refreshes_stale_delivered_state(monkeypatch):
    ticket = _ticket(45, venue="thread")
    state_id = f"ticket_staff_context:{ticket['_id']}"
    states = _ContextRecoveryStates([{
        "_id": state_id,
        "kind": "ticket_staff_context",
        "ticket_id": ticket["_id"],
        "staff_space_id": ticket["location"]["staff_space_id"],
        "delivery_state": "delivered",
        "delivery_attempts": 3,
        "message_id": 900,
        "fingerprint": "stale",
    }])

    class Rest:
        def __init__(self):
            self.edits = 0

        async def edit_message(self, **_kwargs):
            self.edits += 1

        async def create_message(self, **_kwargs):
            raise AssertionError("the existing context must be updated in place")

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", "Updated matching history")

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    rest = Rest()
    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_OpenContextSweepTickets([ticket]),
    )
    result = asyncio.run(console.recover_open_staff_identity_contexts(
        bot=SimpleNamespace(rest=rest),
        mongo=mongo,
        limit=25,
    ))

    assert result == {
        "processed": 1,
        "completed": 1,
        "failed": 0,
        "after_ticket_id": ticket["_id"],
        "exhausted": True,
    }
    assert rest.edits == 1
    assert states.documents[state_id]["delivery_attempts"] == 4
    assert states.documents[state_id]["fingerprint"] != "stale"


def test_cancelled_open_staff_context_sweep_retries_same_ticket(monkeypatch):
    ticket = _ticket(46, venue="thread")
    states = _ContextRecoveryStates([])
    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_OpenContextSweepTickets([ticket]),
    )
    real_delivery = console.deliver_staff_identity_context

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError

    monkeypatch.setattr(console, "deliver_staff_identity_context", cancelled)
    with pytest.raises(asyncio.CancelledError):
        asyncio.run(console.recover_open_staff_identity_contexts(
            bot=object(), mongo=mongo, limit=1
        ))
    assert states.documents == {}

    async def no_context(_mongo, _ticket_doc):
        return None

    monkeypatch.setattr(console, "deliver_staff_identity_context", real_delivery)
    monkeypatch.setattr(console, "build_staff_identity_context", no_context)
    result = asyncio.run(console.recover_open_staff_identity_contexts(
        bot=SimpleNamespace(rest=SimpleNamespace()), mongo=mongo, limit=2
    ))

    assert result["after_ticket_id"] == ticket["_id"]
    assert result["completed"] == 1
    assert result["failed"] == 0


def test_terminal_staff_context_retry_reopens_and_stays_open(monkeypatch):
    ticket = _ticket(22, venue="thread", status="denied")
    ticket["location"].update({
        "guild_id": ticket["guild_id"],
        "staff_parent_id": 523456789012345678,
    })
    state_id = f"ticket_staff_context:{ticket['_id']}"
    states = _ContextRecoveryStates([{
        "_id": state_id,
        "kind": "ticket_staff_context",
        "ticket_id": ticket["_id"],
        "staff_space_id": ticket["location"]["staff_space_id"],
        "delivery_state": "failed",
        "delivery_error": "TimeoutError",
        "created_at": ticket["created_at"],
    }])
    marker = console._staff_context_marker(ticket["_id"])
    components = [
        *console._notice("Applicant context", "Matched history"),
        console.Text(content=f"-# {marker}"),
    ]

    class Messages:
        async def to_list(self):
            return [SimpleNamespace(
                id=900,
                author=SimpleNamespace(id=7),
                components=components,
            )]

    class Rest:
        def __init__(self):
            self.archived = True
            self.locked = True
            self.message_edits = 0
            self.message_creates = 0

        def fetch_messages(self, _channel_id):
            return Messages()

        async def fetch_channel(self, channel_id):
            return SimpleNamespace(
                id=channel_id,
                guild_id=ticket["guild_id"],
                parent_id=ticket["location"]["staff_parent_id"],
                name=console.thread_service.thread_names(
                    ticket["ticket_type"], ticket["ticket_number"], ticket["username"]
                )[1],
                type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
                owner_id=7,
                is_archived=self.archived,
                is_locked=self.locked,
            )

        async def edit_channel(self, _channel_id, **kwargs):
            if "archived" in kwargs:
                self.archived = kwargs["archived"]
            if "locked" in kwargs:
                self.locked = kwargs["locked"]

        async def edit_message(self, **_kwargs):
            self.message_edits += 1

        async def create_message(self, **_kwargs):
            self.message_creates += 1
            raise AssertionError("marker recovery must not create a duplicate")

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", "Matched history")

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    rest = Rest()
    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_ContextRecoveryTickets([ticket]),
    )
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))

    # No re-lock/re-archive step exists any more, so a retried delivery
    # completes in a single pass -- reopened once to deliver the message,
    # then left open rather than restored to locked/archived.
    result = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=bot, mongo=mongo
    ))
    assert result == {"processed": 1, "completed": 1, "failed": 0}
    assert (rest.archived, rest.locked) == (False, False)
    assert rest.message_edits == 1
    assert rest.message_creates == 0
    assert states.documents[state_id]["delivery_state"] == "delivered"


def test_current_terminal_staff_context_recovery_leaves_thread_open(monkeypatch):
    ticket = _ticket(29, venue="thread", status="approved")
    ticket["location"].update({
        "guild_id": ticket["guild_id"],
        "staff_parent_id": 523456789012345678,
    })
    components = console._notice("Applicant context", "Matched history")
    state_id = f"ticket_staff_context:{ticket['_id']}"
    states = _ContextRecoveryStates([{
        "_id": state_id,
        "kind": "ticket_staff_context",
        "ticket_id": ticket["_id"],
        "staff_space_id": ticket["location"]["staff_space_id"],
        "delivery_state": "failed",
        "delivery_error": "TimeoutError",
        "message_id": 900,
        "fingerprint": console._context_fingerprint(components),
    }])

    class Rest:
        def __init__(self):
            self.archived = False
            self.locked = False

        async def fetch_channel(self, channel_id):
            return SimpleNamespace(
                id=channel_id,
                guild_id=ticket["guild_id"],
                parent_id=ticket["location"]["staff_parent_id"],
                name=console.thread_service.thread_names(
                    ticket["ticket_type"], ticket["ticket_number"], ticket["username"]
                )[1],
                type=hikari.ChannelType.GUILD_PUBLIC_THREAD,
                owner_id=7,
                is_archived=self.archived,
                is_locked=self.locked,
            )

        async def edit_channel(self, _channel_id, **_kwargs):
            raise AssertionError(
                "a decision must never archive or lock a thread -- context "
                "already current and thread already open needs no edit"
            )

        async def edit_message(self, **_kwargs):
            raise AssertionError("current context must not be edited")

        async def create_message(self, **_kwargs):
            raise AssertionError("current context must not be duplicated")

    async def context(_mongo, _ticket_doc):
        return console._notice("Applicant context", "Matched history")

    monkeypatch.setattr(console, "build_staff_identity_context", context)
    rest = Rest()
    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_ContextRecoveryTickets([ticket]),
    )
    result = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        mongo=mongo,
    ))

    assert result == {"processed": 1, "completed": 1, "failed": 0}
    assert (rest.archived, rest.locked) == (False, False)


def test_staff_context_recovery_excludes_nonpending_and_clears_no_panel_error(monkeypatch):
    ticket = _ticket(23, venue="thread", status="open")
    state_id = f"ticket_staff_context:{ticket['_id']}"
    future = console.utcnow() + timedelta(minutes=5)
    states = _ContextRecoveryStates([
        {
            "_id": state_id,
            "kind": "ticket_staff_context",
            "ticket_id": ticket["_id"],
            "staff_space_id": ticket["location"]["staff_space_id"],
            "delivery_state": "failed",
            "delivery_error": "RuntimeError",
        },
        {
            "_id": "ticket_staff_context:active",
            "kind": "ticket_staff_context",
            "delivery_state": "pending",
            "lease_until": future,
        },
        {
            "_id": "ticket_staff_context:done",
            "kind": "ticket_staff_context",
            "delivery_state": "delivered",
        },
        {
            "_id": "ticket_staff_context:no-panel",
            "kind": "ticket_staff_context",
            "checked_at": console.utcnow(),
        },
        {
            "_id": "legacy-automation",
            "kind": "legacy_channel_delivery",
            "delivery_state": "failed",
        },
    ])

    class ForbiddenRest:
        def __getattr__(self, name):
            raise AssertionError(f"no Discord call expected: {name}")

    async def no_context(_mongo, _ticket_doc):
        return None

    monkeypatch.setattr(console, "build_staff_identity_context", no_context)
    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_ContextRecoveryTickets([ticket]),
    )
    result = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=SimpleNamespace(rest=ForbiddenRest()), mongo=mongo
    ))

    assert result == {"processed": 1, "completed": 1, "failed": 0}
    assert states.query["kind"] == "ticket_staff_context"
    assert states.documents[state_id]["delivery_state"] == "not_needed"
    assert states.documents[state_id]["delivery_error"] is None


def test_staff_context_missing_or_binding_drift_makes_no_discord_write():
    bound = _ticket(24, venue="thread")
    missing_id = "ticket_missing"
    states = _ContextRecoveryStates([
        {
            "_id": f"ticket_staff_context:{missing_id}",
            "kind": "ticket_staff_context",
            "ticket_id": missing_id,
            "staff_space_id": 1,
            "delivery_state": "failed",
        },
        {
            "_id": f"ticket_staff_context:{bound['_id']}",
            "kind": "ticket_staff_context",
            "ticket_id": bound["_id"],
            "staff_space_id": 999,
            "delivery_state": "pending",
        },
    ])

    class ForbiddenRest:
        def __getattr__(self, name):
            raise AssertionError(f"no Discord call expected: {name}")

    mongo = SimpleNamespace(
        ticket_automation_state=states,
        tickets=_ContextRecoveryTickets([bound]),
    )
    result = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=SimpleNamespace(rest=ForbiddenRest()), mongo=mongo
    ))

    assert result == {"processed": 2, "completed": 0, "failed": 2}
    assert states.documents[f"ticket_staff_context:{missing_id}"]["delivery_state"] == (
        "ticket_missing"
    )
    assert states.documents[f"ticket_staff_context:{bound['_id']}"][
        "delivery_state"
    ] == "binding_invalid"


def test_flag_refresh_queues_only_exact_open_ticket_identities():
    first = _ticket(25, venue="thread")
    second = _ticket(26, venue="thread")
    tickets = _ContextRecoveryTickets([first, second])
    states = _ContextRecoveryStates([])
    mongo = SimpleNamespace(tickets=tickets, ticket_automation_state=states)

    queued = asyncio.run(console._queue_open_staff_context_refreshes(
        mongo,
        discord_ids=[first["user_id"]],
        player_tags=[second["player_tags"][0]],
    ))

    assert [item["_id"] for item in queued] == [first["_id"], second["_id"]]
    assert tickets.query["type"] == "ticket"
    assert tickets.query["venue"] == "thread"
    assert tickets.query["status"] == "open"
    assert {tuple(clause) for clause in tickets.query["$or"]} == {
        ("user_id",),
        ("player_tags",),
        ("player_tag",),
        ("tag",),
    }
    assert set(states.documents) == {
        f"ticket_staff_context:{first['_id']}",
        f"ticket_staff_context:{second['_id']}",
    }
    assert all(
        document["delivery_state"] == "pending"
        and document["refresh_generation"] == 1
        for document in states.documents.values()
    )


def test_flag_refresh_failure_keeps_every_matching_open_context_pending(monkeypatch):
    first = _ticket(27, venue="thread")
    second = _ticket(28, venue="thread")
    states = _ContextRecoveryStates([])
    mongo = SimpleNamespace(
        tickets=_ContextRecoveryTickets([first, second]),
        ticket_automation_state=states,
    )
    attempts = []

    async def unavailable(_bot, _mongo, ticket_doc, **_kwargs):
        attempts.append(ticket_doc["_id"])
        raise TimeoutError("Discord unavailable")

    monkeypatch.setattr(console, "deliver_staff_identity_context", unavailable)
    result = asyncio.run(console.refresh_open_staff_contexts_for_flag_best_effort(
        object(),
        mongo,
        {
            "_id": "flag_123",
            "discord_ids": [first["user_id"]],
            "player_tags": second["player_tags"],
        },
    ))

    assert result is False
    assert attempts == [first["_id"]]
    assert set(states.documents) == {
        f"ticket_staff_context:{first['_id']}",
        f"ticket_staff_context:{second['_id']}",
    }
    assert all(
        item["delivery_state"] == "pending"
        for item in states.documents.values()
    )


def test_flag_refresh_attempts_every_matching_open_staff_panel(monkeypatch):
    first = _ticket(31, venue="thread")
    second = _ticket(32, venue="thread")
    states = _ContextRecoveryStates([])
    mongo = SimpleNamespace(
        tickets=_ContextRecoveryTickets([first, second]),
        ticket_automation_state=states,
    )
    attempts = []

    async def deliver(_bot, _mongo, ticket_doc, **kwargs):
        attempts.append((ticket_doc["_id"], kwargs))
        return 900

    monkeypatch.setattr(console, "deliver_staff_identity_context", deliver)
    result = asyncio.run(console.refresh_open_staff_contexts_for_flag_best_effort(
        object(),
        mongo,
        {
            "_id": "flag_all",
            "discord_ids": [first["user_id"]],
            "player_tags": second["player_tags"],
        },
    ))

    assert result is True
    assert [item[0] for item in attempts] == [first["_id"], second["_id"]]
    assert all(item[1] == {"open_only_refresh": True} for item in attempts)


def test_new_flag_refresh_generation_cannot_be_lost_by_older_delivery_finish():
    ticket = _ticket(33, venue="thread")
    state_id = f"ticket_staff_context:{ticket['_id']}"
    states = _ContextRecoveryStates([{
        "_id": state_id,
        "kind": "ticket_staff_context",
        "ticket_id": ticket["_id"],
        "staff_space_id": ticket["location"]["staff_space_id"],
        "delivery_state": "pending",
        "refresh_generation": 0,
        "lease_owner": "older-delivery",
        "lease_until": console.utcnow() + timedelta(minutes=2),
    }])
    mongo = SimpleNamespace(
        tickets=_ContextRecoveryTickets([ticket]),
        ticket_automation_state=states,
    )

    asyncio.run(console._queue_open_staff_context_refreshes(
        mongo,
        discord_ids=[ticket["user_id"]],
        player_tags=[],
    ))
    finished = asyncio.run(console._finish_staff_context_lease(
        mongo,
        state_id,
        "older-delivery",
        refresh_generation=0,
        message_id=900,
        fingerprint="old",
    ))

    state = states.documents[state_id]
    assert finished is False
    assert state["refresh_generation"] == 1
    assert state["delivery_state"] == "pending"


def test_flag_refresh_never_edits_a_ticket_that_became_terminal(monkeypatch):
    ticket = _ticket(30, venue="thread", status="denied")
    states = _ContextRecoveryStates([])
    mongo = SimpleNamespace(
        tickets=_ContextRecoveryTickets([ticket]),
        ticket_automation_state=states,
    )

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("terminal flag refresh must not reach Discord")

    monkeypatch.setattr(console, "deliver_staff_identity_context", forbidden)
    result = asyncio.run(console.refresh_open_staff_contexts_for_flag_best_effort(
        object(),
        mongo,
        {
            "_id": "flag_terminal",
            "discord_ids": [ticket["user_id"]],
            "player_tags": [],
        },
    ))

    state = states.documents[f"ticket_staff_context:{ticket['_id']}"]
    assert result is True
    assert state["delivery_state"] == "not_needed"
    assert state["open_only_refresh"] is True


def test_best_effort_refresh_never_raises_after_committed_work(monkeypatch):
    async def unavailable(*_args, **_kwargs):
        raise RuntimeError("mongo unavailable")

    monkeypatch.setattr(console, "request_hub_refresh", unavailable)
    assert asyncio.run(console.request_hub_refresh_best_effort(
        object(), object(), reason="committed",
    )) is False


def test_console_channel_validation_is_private_typed_and_permission_complete(monkeypatch):
    guild_id = 123456789012345678
    bot_role_id = 223456789012345678
    recruiter_role_id = 323456789012345678
    everyone = SimpleNamespace(
        id=guild_id, permissions=hikari.Permissions.VIEW_CHANNEL, is_managed=False,
    )
    bot_role = SimpleNamespace(
        id=bot_role_id, permissions=hikari.Permissions.NONE, is_managed=True,
    )
    recruiter_role = SimpleNamespace(
        id=recruiter_role_id, permissions=hikari.Permissions.NONE, is_managed=False,
    )
    roles = [everyone, bot_role, recruiter_role]
    channel = SimpleNamespace(
        id=444,
        guild_id=guild_id,
        type=hikari.ChannelType.GUILD_TEXT,
        permission_overwrites=[
            SimpleNamespace(
                id=guild_id,
                deny=hikari.Permissions.VIEW_CHANNEL,
                allow=hikari.Permissions.NONE,
            ),
            SimpleNamespace(
                id=bot_role_id,
                deny=hikari.Permissions.NONE,
                allow=console.REQUIRED_HUB_BOT_PERMISSIONS,
            ),
            SimpleNamespace(
                id=recruiter_role_id,
                deny=hikari.Permissions.NONE,
                allow=console.REQUIRED_HUB_RECRUITER_PERMISSIONS,
            ),
        ],
    )

    class Rest:
        async def fetch_channel(self, _channel_id):
            return channel

        async def fetch_guild(self, _guild_id):
            return SimpleNamespace(owner_id=999)

        async def fetch_member(self, _guild_id, _member_id):
            if _member_id == 10:
                return SimpleNamespace(id=10, role_ids=(bot_role_id,))
            if _member_id == 20:
                return SimpleNamespace(id=20, role_ids=())
            raise AssertionError(f"unexpected member {_member_id}")

        async def fetch_roles(self, _guild_id):
            return roles

    async def recruiter_roles(_mongo):
        return recruiter_role_id, None

    monkeypatch.setattr(console.perms, "recruiter_role_ids", recruiter_roles)
    bot = SimpleNamespace(rest=Rest(), get_me=lambda: SimpleNamespace(id=10))

    assert asyncio.run(console.validate_console_channel(
        bot, object(), guild_id=guild_id, channel_id=444,
    )) is channel

    rogue_role_id = 523456789012345678
    rogue_role = SimpleNamespace(
        id=rogue_role_id, permissions=hikari.Permissions.NONE, is_managed=False,
    )
    roles.append(rogue_role)
    channel.permission_overwrites.append(SimpleNamespace(
        id=rogue_role_id,
        type=hikari.PermissionOverwriteType.ROLE,
        deny=hikari.Permissions.NONE,
        allow=hikari.Permissions.VIEW_CHANNEL,
    ))
    with pytest.raises(console.ConsoleConfigurationError, match="non-recruiter role"):
        asyncio.run(console.validate_console_channel(
            bot, object(), guild_id=guild_id, channel_id=444,
        ))
    roles.pop()
    channel.permission_overwrites.pop()

    channel.permission_overwrites.append(SimpleNamespace(
        id=20,
        type=hikari.PermissionOverwriteType.MEMBER,
        deny=hikari.Permissions.NONE,
        allow=hikari.Permissions.VIEW_CHANNEL,
    ))
    with pytest.raises(console.ConsoleConfigurationError, match="non-recruiter member"):
        asyncio.run(console.validate_console_channel(
            bot, object(), guild_id=guild_id, channel_id=444,
        ))
    channel.permission_overwrites.pop()

    channel.type = hikari.ChannelType.GUILD_VOICE
    with pytest.raises(console.ConsoleConfigurationError, match="guild text"):
        asyncio.run(console.validate_console_channel(
            bot, object(), guild_id=guild_id, channel_id=444,
        ))
    channel.type = hikari.ChannelType.GUILD_TEXT

    channel.permission_overwrites[0].deny = hikari.Permissions.NONE
    with pytest.raises(console.ConsoleConfigurationError, match="@everyone"):
        asyncio.run(console.validate_console_channel(
            bot, object(), guild_id=guild_id, channel_id=444,
        ))

    channel.permission_overwrites[0].deny = hikari.Permissions.VIEW_CHANNEL
    channel.permission_overwrites[1].allow &= ~hikari.Permissions.ATTACH_FILES
    with pytest.raises(console.ConsoleConfigurationError, match="ATTACH_FILES"):
        asyncio.run(console.validate_console_channel(
            bot, object(), guild_id=guild_id, channel_id=444,
        ))


@pytest.mark.parametrize(
    ("failure", "selected_channel_id", "message"),
    [
        (
            "missing",
            999,
            "saved console channel ID 444 is missing.*relocation is disabled",
        ),
        (
            "inaccessible",
            999,
            "saved console channel ID 444 is inaccessible.*relocation is disabled",
        ),
        (
            "missing",
            444,
            "saved console channel ID 444 is missing.*relocation is disabled",
        ),
        (
            "inaccessible",
            444,
            "saved console channel ID 444 is inaccessible.*relocation is disabled",
        ),
    ],
)
def test_saved_console_channel_failure_is_explicit_and_never_rebinds(
    monkeypatch,
    failure,
    selected_channel_id,
    message,
):
    class MissingChannel(Exception):
        pass

    class InaccessibleChannel(Exception):
        pass

    class Collection:
        def __init__(self):
            self.document = {
                "_id": console.HUB_STATE_ID,
                "guild_id": 321,
                "channel_id": 444,
                "message_id": 555,
            }
            self.updates = []

        async def find_one(self, _query):
            return copy.deepcopy(self.document)

        async def update_one(self, *args, **kwargs):
            self.updates.append((args, kwargs))

    class Rest:
        async def fetch_channel(self, channel_id):
            assert channel_id == 444
            if failure == "missing":
                raise MissingChannel
            raise InaccessibleChannel

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("an unavailable saved channel reached configuration")

    monkeypatch.setattr(console.hikari, "NotFoundError", MissingChannel)
    monkeypatch.setattr(console.hikari, "ForbiddenError", InaccessibleChannel)
    monkeypatch.setattr(console, "validate_console_channel", forbidden)
    monkeypatch.setattr(console, "refresh_hub_now", forbidden)
    collection = Collection()
    before = copy.deepcopy(collection.document)

    with pytest.raises(console.ConsoleConfigurationError, match=message):
        asyncio.run(console.configure_hub_here(
            SimpleNamespace(rest=Rest()),
            SimpleNamespace(ticket_setup=collection),
            guild_id=321,
            channel_id=selected_channel_id,
        ))

    assert collection.document == before
    assert collection.updates == []


def test_existing_saved_console_keeps_one_console_rejection_without_rebinding(
    monkeypatch,
):
    class Collection:
        def __init__(self):
            self.document = {
                "_id": console.HUB_STATE_ID,
                "guild_id": 321,
                "channel_id": 444,
                "message_id": 555,
            }
            self.updates = []

        async def find_one(self, _query):
            return copy.deepcopy(self.document)

        async def update_one(self, *args, **kwargs):
            self.updates.append((args, kwargs))

    class Rest:
        async def fetch_channel(self, channel_id):
            assert channel_id == 444
            return SimpleNamespace(id=channel_id)

    async def forbidden(*_args, **_kwargs):
        raise AssertionError("a different channel reached configuration")

    monkeypatch.setattr(console, "validate_console_channel", forbidden)
    monkeypatch.setattr(console, "refresh_hub_now", forbidden)
    collection = Collection()
    before = copy.deepcopy(collection.document)

    with pytest.raises(
        console.ConsoleConfigurationError,
        match="one console is already configured in another channel",
    ):
        asyncio.run(console.configure_hub_here(
            SimpleNamespace(rest=Rest()),
            SimpleNamespace(ticket_setup=collection),
            guild_id=321,
            channel_id=999,
        ))

    assert collection.document == before
    assert collection.updates == []


def test_deleted_hub_message_is_recreated_and_new_id_is_saved(monkeypatch):
    class MissingMessage(Exception):
        pass

    class Rest:
        def __init__(self):
            self.edits = 0
            self.creates = 0

        async def edit_message(self, **_kwargs):
            self.edits += 1
            raise MissingMessage

        async def create_message(self, **_kwargs):
            self.creates += 1
            return SimpleNamespace(id=999)

        def fetch_messages(self, _channel_id):
            return SimpleNamespace(to_list=lambda: _empty_messages())

    class Collection:
        def __init__(self):
            self.updates = []

        async def update_one(self, query, update, **_kwargs):
            self.updates.append((query, update))

    async def payload(_mongo):
        return []

    async def valid(*_args, **_kwargs):
        return object()

    async def _empty_messages():
        return []

    async def signature(_mongo):
        return "sig"

    monkeypatch.setattr(console.hikari, "NotFoundError", MissingMessage)
    monkeypatch.setattr(console, "_hub_payload", payload)
    monkeypatch.setattr(console, "_chart_signature", signature)
    monkeypatch.setattr(console, "validate_console_channel", valid)
    collection = Collection()
    mongo = SimpleNamespace(ticket_setup=collection)
    rest = Rest()
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))

    message_id = asyncio.run(console._publish_hub(
        bot,
        mongo,
        {"guild_id": 321, "channel_id": 123, "message_id": 456},
    ))

    assert message_id == 999
    assert (rest.edits, rest.creates) == (1, 1)
    # The message binding is written unconditionally; the settle that clears
    # force_pending is a separate, revision-guarded write.
    sets = [update["$set"] for _query, update in collection.updates]
    assert any(fields.get("message_id") == 999 for fields in sets)
    settle_query, settle_update = collection.updates[-1]
    assert "desired_revision" in settle_query
    assert settle_update["$set"]["force_pending"] is False
    assert settle_update["$set"]["chart_signature"] == "sig"


def test_orphaned_hub_is_reused_after_create_checkpoint_loss(monkeypatch):
    hub = SimpleNamespace(
        id=777,
        author=SimpleNamespace(id=7),
        components=[SimpleNamespace(components=[
            SimpleNamespace(custom_id="ticket_v2_console_pick:hub"),
            SimpleNamespace(custom_id="ticket_v2_console_find:hub"),
        ])],
    )

    class Messages:
        def __init__(self):
            self.messages = [
                SimpleNamespace(
                    id=1000 + index,
                    author=SimpleNamespace(id=7),
                    components=[],
                )
                for index in range(150)
            ] + [hub]

        def limit(self, amount):
            return SimpleNamespace(to_list=lambda: _limited(self.messages, amount))

        async def to_list(self):
            return list(self.messages)

    async def _limited(messages, amount):
        return list(messages[:amount])

    class Rest:
        def __init__(self):
            self.edits = []
            self.creates = 0

        def fetch_messages(self, _channel_id):
            return Messages()

        async def edit_message(self, **kwargs):
            self.edits.append(kwargs)

        async def create_message(self, **_kwargs):
            self.creates += 1
            raise AssertionError("an orphaned shared hub must be reused")

    class Collection:
        def __init__(self):
            self.updates = []

        async def update_one(self, query, update, **_kwargs):
            self.updates.append((query, update))

    async def payload(_mongo):
        return ["fresh payload"]

    async def valid(*_args, **_kwargs):
        return object()

    async def signature(_mongo):
        return "sig"

    monkeypatch.setattr(console, "_hub_payload", payload)
    monkeypatch.setattr(console, "_chart_signature", signature)
    monkeypatch.setattr(console, "validate_console_channel", valid)
    rest = Rest()
    collection = Collection()
    message_id = asyncio.run(console._publish_hub(
        SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7)),
        SimpleNamespace(ticket_setup=collection),
        {"guild_id": 321, "channel_id": 123},
    ))
    assert message_id == 777
    assert rest.creates == 0
    assert rest.edits[0]["message"] == 777
    sets = [update["$set"] for _query, update in collection.updates]
    assert any(fields.get("message_id") == 777 for fields in sets)
    settle_query, settle_update = collection.updates[-1]
    assert "desired_revision" in settle_query
    assert settle_update["$set"]["force_pending"] is False


def test_orphaned_hub_scan_is_bounded_to_the_newest_200_messages():
    """The hub is always one of the bot's own most recent console-channel
    messages -- crawling the channel's entire history to find it does not
    scale as unrelated chatter accumulates there."""
    hub = SimpleNamespace(
        id=777,
        author=SimpleNamespace(id=7),
        components=[SimpleNamespace(components=[
            SimpleNamespace(custom_id="ticket_v2_console_pick:hub"),
            SimpleNamespace(custom_id="ticket_v2_console_find:hub"),
        ])],
    )

    class Messages:
        def __init__(self):
            self.messages = [
                SimpleNamespace(id=1000 + index, author=SimpleNamespace(id=7), components=[])
                for index in range(250)
            ] + [hub]
            self.requested_limit = None

        def limit(self, amount):
            self.requested_limit = amount
            return SimpleNamespace(to_list=lambda: _limited(self.messages, amount))

        async def to_list(self):
            return list(self.messages)

    async def _limited(messages, amount):
        return list(messages[:amount])

    messages = Messages()
    rest = SimpleNamespace(fetch_messages=lambda _channel_id: messages)
    bot = SimpleNamespace(rest=rest, get_me=lambda: SimpleNamespace(id=7))

    orphan = asyncio.run(console._find_orphaned_hub(bot, 123))

    assert messages.requested_limit == console._ORPHANED_HUB_SCAN_LIMIT
    # The hub sits past the 200-message window behind 250 older messages, so
    # a bounded scan must not find it.
    assert orphan is None


def test_hub_publish_stops_before_private_data_render_on_permission_drift(monkeypatch):
    calls = []

    async def drift(*_args, **_kwargs):
        calls.append("validate")
        raise console.ConsoleConfigurationError(
            "non-recruiter role can view the console channel"
        )

    async def forbidden_payload(*_args, **_kwargs):
        raise AssertionError("private hub data rendered after visibility drift")

    class Rest:
        async def edit_message(self, **_kwargs):
            raise AssertionError("hub edited after visibility drift")

        async def create_message(self, **_kwargs):
            raise AssertionError("hub created after visibility drift")

    monkeypatch.setattr(console, "validate_console_channel", drift)
    monkeypatch.setattr(console, "_hub_payload", forbidden_payload)
    with pytest.raises(console.ConsoleConfigurationError, match="non-recruiter"):
        asyncio.run(console._publish_hub(
            SimpleNamespace(rest=Rest()),
            object(),
            {"guild_id": 321, "channel_id": 123, "message_id": 456},
        ))
    assert calls == ["validate"]


def test_hub_skips_render_when_chart_signature_is_unchanged_and_not_forced(
    monkeypatch,
):
    """A candidate's own message (force_pending=False) must not repeat the
    Pillow render and Discord PNG re-upload when the chart's own inputs --
    console_counts and flag counts -- have not moved since the last publish."""

    async def counts(_mongo):
        return {"statuses": {"open": 3}, "by_type": {"main": {"open": 2}, "fwa": {"open": 1}}}

    async def flags(_mongo):
        return {"blacklisted": 1}

    async def valid(*_args, **_kwargs):
        return object()

    async def forbidden_payload(_mongo):
        raise AssertionError("chart re-rendered despite an unchanged signature")

    class Rest:
        async def edit_message(self, **_kwargs):
            raise AssertionError("hub edited despite an unchanged signature")

    monkeypatch.setattr(console.store, "console_counts", counts)
    monkeypatch.setattr(console.flag_store, "count_active", flags)
    monkeypatch.setattr(console, "validate_console_channel", valid)
    monkeypatch.setattr(console, "_hub_payload", forbidden_payload)

    signature = asyncio.run(console._chart_signature(object()))
    message_id = asyncio.run(console._publish_hub(
        SimpleNamespace(rest=Rest()),
        object(),
        {
            "guild_id": 321, "channel_id": 123, "message_id": 456,
            "force_pending": False, "chart_signature": signature,
        },
    ))

    assert message_id == 456


def test_hub_forces_a_redraw_when_force_pending_even_if_counts_would_match(
    monkeypatch,
):
    """A ticket create/decide/flag event always sets force_pending, and it
    must force a full redraw even when the totals happen to net out
    unchanged -- the open-ticket picker's set membership can differ without
    moving any total."""

    async def counts(_mongo):
        return {"statuses": {"open": 3}}

    async def flags(_mongo):
        return {}

    async def valid(*_args, **_kwargs):
        return object()

    async def payload(_mongo):
        return ["FRESH PANEL"]

    class Collection:
        def __init__(self):
            self.updates = []

        async def update_one(self, *args, **kwargs):
            self.updates.append((args, kwargs))

    class Rest:
        def __init__(self):
            self.edits = 0

        async def edit_message(self, **_kwargs):
            self.edits += 1

    monkeypatch.setattr(console.store, "console_counts", counts)
    monkeypatch.setattr(console.flag_store, "count_active", flags)
    monkeypatch.setattr(console, "validate_console_channel", valid)
    monkeypatch.setattr(console, "_hub_payload", payload)

    rest = Rest()
    collection = Collection()
    message_id = asyncio.run(console._publish_hub(
        SimpleNamespace(rest=rest),
        SimpleNamespace(ticket_setup=collection),
        {"guild_id": 321, "channel_id": 123, "message_id": 456, "force_pending": True},
    ))

    assert message_id == 456
    assert rest.edits == 1
    query, update = collection.updates[0][0]
    assert query == {"_id": console.HUB_STATE_ID, "desired_revision": 0}
    assert update["$set"]["force_pending"] is False
    # The forced (full-redraw) path must still store the signature of what
    # was actually drawn, so a later non-forced publish has a real baseline
    # to compare against instead of stale or missing data.
    assert "chart_signature" in update["$set"]


def test_force_raised_mid_publish_survives_the_settle_write(monkeypatch):
    """A ticket change that lands while the hub is being redrawn calls
    _mark_hub_dirty again, bumping desired_revision and re-raising
    force_pending. The settle write at the end of the publish that was
    already in flight must not clobber that -- it is conditioned on the
    desired_revision read at entry, so the next drain redraws instead of
    leaving a stale picker forever."""

    async def counts(_mongo):
        return {"statuses": {"open": 3}}

    async def flags(_mongo):
        return {}

    async def valid(*_args, **_kwargs):
        return object()

    async def payload(_mongo):
        return ["FRESH PANEL"]

    class Collection:
        def __init__(self, document):
            self.document = document
            self.updates = []

        async def update_one(self, query, update, **_kwargs):
            self.updates.append((query, update))
            if all(self.document.get(key) == value for key, value in query.items()):
                for key, value in update.get("$set", {}).items():
                    self.document[key] = value

    class Rest:
        def __init__(self):
            self.edits = 0

        async def edit_message(self, **_kwargs):
            self.edits += 1

    monkeypatch.setattr(console.store, "console_counts", counts)
    monkeypatch.setattr(console.flag_store, "count_active", flags)
    monkeypatch.setattr(console, "validate_console_channel", valid)
    monkeypatch.setattr(console, "_hub_payload", payload)

    rest = Rest()
    document = {
        "_id": console.HUB_STATE_ID,
        "guild_id": 321, "channel_id": 123, "message_id": 456,
        "force_pending": True, "desired_revision": 5,
    }
    collection = Collection(document)
    state = dict(document)

    # A ticket change lands mid-publish: _mark_hub_dirty bumps
    # desired_revision and re-raises force_pending before this publish's
    # settle write runs.
    document["desired_revision"] = 6
    document["force_pending"] = True

    message_id = asyncio.run(console._publish_hub(
        SimpleNamespace(rest=rest),
        SimpleNamespace(ticket_setup=collection),
        state,
    ))

    assert message_id == 456
    assert rest.edits == 1
    # The settle write's filter (desired_revision == 5, the entry snapshot)
    # no longer matches the document (now at 6), so it must not apply.
    assert document["force_pending"] is True
    assert document["desired_revision"] == 6


def test_flag_manager_back_button_uses_a_real_arrow_emoji():
    ticket_doc = _ticket()
    view = console.build_flag_manager(ticket_doc, action_id="abc", flags=[])
    nodes = _nodes(view)
    back_button = next(
        node for node in nodes
        if isinstance(node, dict)
        and str(node.get("custom_id", "")).startswith("ticket_v2_flag_back")
    )
    glyph = back_button["emoji"]["name"]
    assert ord(glyph[0]) == 0x2B05
    assert glyph == "⬅️"


def test_clean_neutralizes_headings_masked_links_and_newlines():
    injected = "IGN Bob\n## Verified\n[Open](https://x)"
    cleaned = console._clean(injected)
    assert "\n" not in cleaned
    assert not any(line.strip().startswith("#") for line in cleaned.split("\n"))
    assert "](" not in cleaned


def test_clean_code_span_never_escapes_and_strips_backticks_and_newlines():
    assert console._clean_code_span("#2PP0JCCLU") == "#2PP0JCCLU"
    assert console._clean_code_span("weird`tick\nid") == "weirdtick id"
    assert console._clean_code_span(None) == "Unknown"
    assert console._clean_code_span("x" * 200, limit=5) == "xxxxx"


def test_player_tag_in_code_span_has_no_backslash_escape():
    ticket = _ticket(21, player_tags=["#2PP0JCCLU"])
    view = console.build_ticket_detail(
        ticket, action_id="h" * 32, flags=[], history=[],
    )
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "`#2PP0JCCLU`" in content
    assert "\\#2PP0JCCLU" not in content


def test_detail_panel_shows_thread_removed_when_candidate_thread_is_missing():
    ticket = _ticket(22, thread_missing={"thread_role": "candidate"})
    view = console.build_ticket_detail(
        ticket, action_id="i" * 32, flags=[], history=[],
    )
    nodes = _nodes(view)
    removed_button = next(
        node for node in nodes
        if isinstance(node, dict)
        and str(node.get("custom_id", "")).startswith("ticket_v2_console_unavailable:thread|")
        and str(node.get("custom_id", "")).endswith("|candidate")
    )
    assert removed_button["label"] == "Thread removed"
    assert removed_button["disabled"] is True
    labels = [node.get("label") for node in nodes if isinstance(node, dict) and "label" in node]
    assert "Open the thread" not in labels
    assert "Open staff thread" in labels


def test_applicant_intake_text_cannot_inject_headings_or_masked_links():
    injected = "IGN Bob\n## Verified\n[Open](https://x)"
    ticket_doc = _ticket(15, intake_snapshot={"looking_for": injected})
    view = console.build_ticket_detail(
        ticket_doc, action_id="e" * 32, flags=[], history=[],
    )
    rendered = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    applicant_line = next(
        line for line in rendered.split("\n")
        if "What they want from a clan" in line
    )
    assert not applicant_line.strip().startswith("#")
    assert "](" not in applicant_line
    assert "]\\(" in applicant_line or "\\[Open\\]" in applicant_line


def test_no_ticket_component_emoji_uses_a_bare_arrow_codepoint():
    package_dir = Path(__file__).resolve().parents[1] / "extensions" / "commands" / "tickets"
    offenders = []
    for path in sorted(package_dir.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r'emoji\s*=\s*"([^"]*)"', text):
            value = match.group(1)
            if any(0x2190 <= ord(ch) <= 0x21FF for ch in value):
                offenders.append((path.name, value))
    assert offenders == []
