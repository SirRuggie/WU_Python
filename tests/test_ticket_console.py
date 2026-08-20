import asyncio
import copy
import json
from datetime import datetime, timedelta, timezone
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


def test_shared_hub_has_only_chart_picker_and_find_and_uploads_a_fresh_png():
    view = console.build_hub_components([_ticket(index) for index in range(1, 26)], b"png")
    container, attachments = view[0].build()

    assert len(container["components"]) == 3
    assert [child["type"] for child in container["components"]] == [
        hikari.ComponentType.MEDIA_GALLERY,
        hikari.ComponentType.ACTION_ROW,
        hikari.ComponentType.ACTION_ROW,
    ]
    assert [attachment.filename for attachment in attachments] == ["ticket_overview.png"]
    select = container["components"][1]["components"][0]
    assert len(select["options"]) == 25
    assert all(option["value"].startswith("ticket_") for option in select["options"])
    _assert_component_limits(view)


def test_empty_hub_keeps_a_valid_disabled_picker():
    view = console.build_hub_components([], b"png")
    container, _attachments = view[0].build()
    select = container["components"][1]["components"][0]
    assert select["disabled"] is True
    assert [option["label"] for option in select["options"]] == ["No open tickets"]
    _assert_component_limits(view)


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
        if str(node.get("custom_id", "")).startswith("ticket_console_view:")
    ]
    assert len(view_buttons) == 10
    assert any(node.get("label") == "New search" for node in _nodes(view))
    _assert_component_limits(view)


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


def test_staff_context_reserves_complete_marker_in_worst_case_payload(monkeypatch):
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
    marker = f"-# {console._staff_context_marker(ticket['_id'])}"
    payload = [*view, console.Text(content=marker)]
    contents = [
        str(node["content"]) for node in _nodes(payload) if "content" in node
    ]

    assert contents[-1] == marker
    assert all("**Why:**" in content for content in contents[1:9])
    _assert_component_limits(payload)


def test_lock_contention_panel_does_not_claim_a_blacklist_exists():
    view = console._transition_result_panel(
        console.store.Transition(
            console.store.BLOCKED,
            _ticket(18),
            "applicant identity is being updated; try again",
        ),
        verb="approved",
    )
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Approval not completed" in content
    assert "try again" in content
    assert "blacklist" not in content.casefold()


def test_effect_failure_panel_reports_durable_automatic_retry():
    view = console._transition_result_panel(
        console.store.Transition(
            console.store.EFFECT_FAILED,
            _ticket(19, status="approved"),
            "thread archive is pending",
        ),
        verb="approved",
    )
    content = "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )
    assert "Decision recorded; updates retrying" in content
    assert resolve.RESOLUTION_EFFECT_RETRY_MESSAGE in content
    assert "notification failed" not in content.casefold()


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
    assert "Captured answer transcript" in transcript_text
    assert "Candidate answer 1" not in transcript_text
    assert "Candidate answer 2" in transcript_text
    assert "Candidate answer 7" in transcript_text
    _assert_component_limits(transcript_view)


def test_shared_hub_actions_are_no_return_so_dispatcher_cannot_edit_the_root():
    pick = dispatcher.registered_functions["ticket_console_pick"]
    find = dispatcher.registered_functions["ticket_console_find"]
    assert pick.no_return is True
    assert find.no_return is True
    assert find.opens_modal is True
    assert find.preload_state is False
    assert dispatcher.registered_functions["ticket_console_view"].requires_state is True
    again = dispatcher.registered_functions["ticket_console_search_again"]
    assert again.opens_modal is True
    assert again.no_return is True
    assert again.preload_state is False
    deny = dispatcher.registered_functions["ticket_console_deny"]
    assert deny.opens_modal is True
    assert deny.no_return is True
    assert deny.preload_state is False
    root_submit = dispatcher.registered_functions["ticket_console_find_root_submit"]
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
        "ticket_console_find:hub",
        "ticket_console_search_again:search",
        "ticket_console_deny:detail",
    ):
        asyncio.run(dispatcher._dispatch(Context(custom_id), object()))

    assert modals == [
        "ticket_console_find_root_submit:33",
        "ticket_console_find_submit:search",
        "ticket_console_deny_submit:detail",
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
        "ticket_console_find_root_submit:33",
        "ticket_console_find_submit:search",
        "ticket_console_deny_submit:detail",
        "ticket_console_find_root_submit:33",
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
            "type": "ticket_console_search",
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
            "type": "ticket_console_detail",
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
        "type": "ticket_console_detail",
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

    assert [event[0] for event in events] == [
        "defer", "envelope", "permission", "private-state", "transition", "edit",
    ]


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


def test_terminal_staff_context_retry_converges_locked_after_restore_failure(monkeypatch):
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
            self.restore_failures = 1
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
            if kwargs.get("locked") is True and kwargs.get("archived") is True:
                if self.restore_failures:
                    self.restore_failures -= 1
                    raise TimeoutError("restore acknowledgement lost")
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

    first = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=bot, mongo=mongo
    ))
    assert first == {"processed": 1, "completed": 0, "failed": 1}
    assert (rest.archived, rest.locked) == (False, False)
    assert states.documents[state_id]["delivery_state"] == "failed"

    second = asyncio.run(console.recover_pending_staff_identity_contexts(
        bot=bot, mongo=mongo
    ))
    assert second == {"processed": 1, "completed": 1, "failed": 0}
    assert (rest.archived, rest.locked) == (True, True)
    assert rest.message_edits == 2
    assert rest.message_creates == 0
    assert states.documents[state_id]["delivery_state"] == "delivered"


def test_current_terminal_staff_context_still_converges_locked_and_archived(monkeypatch):
    ticket = _ticket(29, venue="thread", status="approved")
    ticket["location"].update({
        "guild_id": ticket["guild_id"],
        "staff_parent_id": 523456789012345678,
    })
    marker = console._staff_context_marker(ticket["_id"])
    components = [
        *console._notice("Applicant context", "Matched history"),
        console.Text(content=f"-# {marker}"),
    ]
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
            self.channel_edits = 0

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
            self.channel_edits += 1
            self.archived = kwargs["archived"]
            self.locked = kwargs["locked"]

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
    assert (rest.archived, rest.locked) == (True, True)
    assert rest.channel_edits == 1


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
            self.update = None

        async def update_one(self, query, update, **_kwargs):
            self.update = (query, update)

    async def payload(_mongo):
        return []

    async def valid(*_args, **_kwargs):
        return object()

    async def _empty_messages():
        return []

    monkeypatch.setattr(console.hikari, "NotFoundError", MissingMessage)
    monkeypatch.setattr(console, "_hub_payload", payload)
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
    assert collection.update[1]["$set"]["message_id"] == 999


def test_orphaned_hub_is_reused_after_create_checkpoint_loss(monkeypatch):
    hub = SimpleNamespace(
        id=777,
        author=SimpleNamespace(id=7),
        components=[SimpleNamespace(components=[
            SimpleNamespace(custom_id="ticket_console_pick:hub"),
            SimpleNamespace(custom_id="ticket_console_find:hub"),
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
            self.update = None

        async def update_one(self, query, update, **_kwargs):
            self.update = (query, update)

    async def payload(_mongo):
        return ["fresh payload"]

    async def valid(*_args, **_kwargs):
        return object()

    monkeypatch.setattr(console, "_hub_payload", payload)
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
    assert collection.update[1]["$set"]["message_id"] == 777


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
