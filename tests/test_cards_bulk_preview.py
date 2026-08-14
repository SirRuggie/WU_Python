"""Structural and interaction pins for the synthetic bulk-editor phone lab."""

import asyncio
import inspect
from pathlib import Path
from types import SimpleNamespace

import hikari
import pytest

from extensions.commands import cards_bulk_preview as preview
from utils import cards


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


def _text(view):
    return "\n".join(
        str(node["content"]) for node in _nodes(view) if "content" in node
    )


def _labels(view):
    return [
        str(node["label"])
        for node in _nodes(view)
        if node.get("type") == int(hikari.ComponentType.BUTTON)
    ]


def _custom_ids(view):
    return [str(node["custom_id"]) for node in _nodes(view) if "custom_id" in node]


def _component_count(view):
    return len([node for node in _nodes(view) if "type" in node])


def _assert_payload_limits(view):
    nodes = _nodes(view)
    assert len([node for node in nodes if "type" in node]) <= 40
    custom_ids = [str(node["custom_id"]) for node in nodes if "custom_id" in node]
    assert len(custom_ids) == len(set(custom_ids))
    for custom_id in custom_ids:
        assert len(custom_id) <= 100
        assert custom_id.count(":") == 1
    for node in nodes:
        if "content" in node:
            assert len(str(node["content"])) <= 4_000
        if "placeholder" in node:
            assert len(str(node["placeholder"])) <= 150
        if "label" in node:
            assert len(str(node["label"])) <= 100
        options = node.get("options")
        if options is not None:
            assert 1 <= len(options) <= 25
            assert int(node.get("max_values", 1)) <= len(options)
            assert len({str(option["value"]) for option in options}) == len(options)


class _MenuCtx:
    def __init__(self, *, user_id=preview.OWNER_ID, values=()):
        self.user = SimpleNamespace(id=user_id)
        self.interaction = SimpleNamespace(values=list(values))


class _ModalOpenCtx(_MenuCtx):
    def __init__(self, *, user_id=preview.OWNER_ID, values=()):
        super().__init__(user_id=user_id, values=values)
        self.opened = None
        self.responses = []

    async def respond_with_modal(self, **kwargs):
        self.opened = kwargs

    async def respond(self, **kwargs):
        self.responses.append(kwargs)


class _ModalSubmitCtx(_MenuCtx):
    def __init__(self, values, *, user_id=preview.OWNER_ID):
        super().__init__(user_id=user_id)
        self.sequence = []
        self.edited = None
        self.interaction.components = [
            [SimpleNamespace(custom_id=custom_id, value=value)]
            for custom_id, value in values.items()
        ]
        self.interaction.message = SimpleNamespace(id=42)
        self.interaction.create_initial_response = self._initial
        self.interaction.edit_initial_response = self._edit

    async def _initial(self, response_type, **_kwargs):
        self.sequence.append(("ack", response_type))

    async def _edit(self, components=None, **_kwargs):
        self.sequence.append("edit")
        self.edited = components

    async def defer(self, *_args, **_kwargs):
        self.sequence.append("defer_create")


@pytest.fixture(autouse=True)
def _isolated_preview_sessions():
    preview._PREVIEW_SESSIONS.clear()
    yield
    preview._PREVIEW_SESSIONS.clear()


def _session(key):
    return preview._new_session(preview.OWNER_ID, key)


def test_scenario_definitions_keep_the_requested_order_names_and_card_counts():
    scenarios = preview.BULK_PREVIEW_SCENARIOS
    assert tuple(scenarios) == ("A", "B", "C", "D", "E")
    assert [scenario.name for scenario in scenarios.values()] == [
        "5 scattered changed cards",
        "10 scattered changed cards",
        "All 19 exact counts",
        "19 cards split across 0 / 1 / 2",
        "Rapid correction of 7 selected cards",
    ]
    assert [len(scenario.target_ids) for scenario in scenarios.values()] == [
        5, 10, 19, 19, 7,
    ]

    catalog_positions = {
        card_id: index for index, card_id in enumerate(preview.ELIXIR_IDS)
    }
    for scenario in scenarios.values():
        assert set(scenario.target_ids) <= set(preview.ELIXIR_IDS)
        assert list(scenario.target_ids) == sorted(
            scenario.target_ids, key=catalog_positions.__getitem__
        )
        assert tuple(card_id for card_id, _value in scenario.target_values) == (
            scenario.target_ids
        )

    d_targets = scenarios["D"].targets
    assert tuple(d_targets) == preview.ELIXIR_IDS
    assert set(d_targets.values()) == {0, 1, 2}
    assert scenarios["C"].target_ids == preview.ELIXIR_IDS


def test_category_keeps_reserved_cards_visible_but_out_of_the_chooser():
    session = _session("A")
    view = preview._category_view(session)
    nodes = _nodes(view)
    chooser = next(
        node for node in nodes
        if node.get("type") == int(hikari.ComponentType.TEXT_SELECT_MENU)
    )
    option_ids = tuple(str(option["value"]) for option in chooser["options"])

    assert option_ids == session.editable_ids
    assert not set(option_ids) & set(session.reserved_ids)
    assert chooser["min_values"] == len(session.scenario.target_ids)
    assert chooser["max_values"] == len(session.scenario.target_ids)
    rendered = _text(view)
    for card in preview.ELIXIR_CARDS:
        assert card.name in rendered
    for card_id in session.reserved_ids:
        reserved_line = next(
            line for line in rendered.splitlines()
            if cards.CARD_BY_ID[card_id].name in line
        )
        assert "in a trade" in reserved_line and "locked" in reserved_line
    assert "Choose cards to update" in rendered
    assert "Edit all counts" in _labels(view)
    assert "Preview Member" in rendered and "#PREVIEW" in rendered
    _assert_payload_limits(view)


def test_direct_exact_selection_filters_and_normalizes_before_opening_modal():
    session = _session("A")
    submitted = [
        *reversed(session.scenario.target_ids),
        *session.reserved_ids,
        "not_a_card",
    ]
    ctx = _ModalOpenCtx(values=submitted)

    asyncio.run(preview.cards_bulk_preview_exact_select(
        ctx, f"{session.token}|{session.scope_nonce}"
    ))

    assert session.selected_ids == session.scenario.target_ids
    assert session.operation is not None
    assert session.operation.card_ids == session.scenario.target_ids
    assert ctx.opened is not None and ctx.responses == []
    assert len(ctx.opened["components"]) == 5
    assert ctx.opened["custom_id"].startswith(
        f"cards_bulk_preview_exact_submit:{session.token}|"
    )


def test_workbench_names_the_full_scope_and_exposes_all_candidate_actions():
    session = _session("E")
    session.selected_ids = session.scenario.target_ids
    view = preview._workbench_view(session)
    rendered = _text(view)

    assert "7 selected cards" in rendered
    assert "ALL 7 SELECTED CARDS" in rendered
    for card_id in session.selected_ids:
        assert cards.CARD_BY_ID[card_id].name in rendered
        assert f"`{session.draft_counts[card_id]}`" in rendered
    assert {
        "Different counts",
        "Review one at a time",
        "0",
        "1",
        "2",
        "Other",
        "Change selection",
        "Cancel",
    } <= set(_labels(view))
    _assert_payload_limits(view)


def test_exact_modal_batches_partition_19_as_five_five_five_four():
    session = _session("C")
    operation = preview._begin_operation(session, "edit_all", session.editable_ids)

    payloads = [
        preview._exact_modal_payload(session, operation, start)
        for start in (0, 5, 10, 15)
    ]
    assert [len(payload["components"]) for payload in payloads] == [5, 5, 5, 4]
    assert [payload["title"] for payload in payloads] == [
        "Preview counts · 1-5 of 19",
        "Preview counts · 6-10 of 19",
        "Preview counts · 11-15 of 19",
        "Preview counts · 16-19 of 19",
    ]
    for payload in payloads:
        assert len(payload["title"]) <= 45
        assert len(payload["custom_id"]) <= 100
        assert payload["custom_id"].count(":") == 1


def test_modal_submit_edits_to_progress_and_requires_explicit_next_five():
    session = _session("C")
    operation = preview._begin_operation(session, "edit_all", session.editable_ids)
    first_batch = operation.card_ids[:5]
    ctx = _ModalSubmitCtx({f"q{index}": str(index) for index in range(5)})

    asyncio.run(preview.cards_bulk_preview_exact_submit(
        ctx, f"{session.token}|{operation.token}|0"
    ))

    assert ctx.sequence == [
        ("ack", hikari.ResponseType.DEFERRED_MESSAGE_UPDATE),
        "edit",
    ]
    assert operation.next_index == 5
    assert [session.draft_counts[card_id] for card_id in first_batch] == list(range(5))
    assert "Next five" in _labels(ctx.edited)
    assert "Discord cannot open the next modal from a modal submit" in _text(ctx.edited)

    next_id = next(
        custom_id for custom_id in _custom_ids(ctx.edited)
        if custom_id.startswith("cards_bulk_preview_exact_next:")
    )
    next_ctx = _ModalOpenCtx()
    asyncio.run(preview.cards_bulk_preview_exact_next(
        next_ctx, next_id.partition(":")[2]
    ))
    assert next_ctx.opened is not None
    assert len(next_ctx.opened["components"]) == 5


def test_same_value_waits_for_confirmation_then_changes_only_selected_draft():
    session = _session("D")
    _label, selected = preview._selection_target(session)
    session.selected_ids = selected
    nonce = session.scope_nonce
    baseline = dict(session.baseline_counts)
    before = dict(session.draft_counts)
    ctx = _MenuCtx()

    confirmation = asyncio.run(preview.cards_bulk_preview_bulk_choice(
        ctx, f"{session.token}|{nonce}|0"
    ))

    assert session.draft_counts == before
    assert f"{len(selected)} selected cards" in _text(confirmation)
    assert f"Set all {len(selected)} to 0?" in _text(confirmation)
    assert set(_labels(confirmation)) == {"Set all to 0", "Back"}
    for card_id in selected:
        assert cards.CARD_BY_ID[card_id].name in _text(confirmation)

    result = asyncio.run(preview.cards_bulk_preview_bulk_apply(
        ctx, f"{session.token}|{nonce}|0"
    ))
    assert all(session.draft_counts[card_id] == 0 for card_id in selected)
    assert all(
        session.draft_counts[card_id] == before[card_id]
        for card_id in preview.ELIXIR_IDS if card_id not in selected
    )
    assert session.baseline_counts == baseline
    assert "Choose the next marked group" in _text(result)


def test_rapid_queue_skip_preserves_value_and_every_answer_auto_advances():
    session = _session("E")
    session.selected_ids = session.scenario.target_ids
    operation = preview._begin_operation(session, "rapid", session.selected_ids)
    ctx = _MenuCtx()
    skipped_id = operation.card_ids[0]
    skipped_before = session.draft_counts[skipped_id]

    second = asyncio.run(preview.cards_bulk_preview_rapid_skip(
        ctx, f"{session.token}|{operation.token}|0"
    ))
    assert operation.next_index == 1
    assert session.draft_counts[skipped_id] == skipped_before
    assert "2 of 7" in _text(second)

    changed_id = operation.card_ids[1]
    third = asyncio.run(preview.cards_bulk_preview_rapid_set(
        ctx, f"{session.token}|{operation.token}|1|2"
    ))
    assert operation.next_index == 2
    assert session.draft_counts[changed_id] == 2
    assert "3 of 7" in _text(third)

    view = third
    while operation.next_index < len(operation.card_ids):
        index = operation.next_index
        view = asyncio.run(preview.cards_bulk_preview_rapid_set(
            ctx, f"{session.token}|{operation.token}|{index}|1"
        ))
    assert operation.next_index == 7
    assert "Rapid queue review" in _text(view)
    assert "Sandbox complete" in _text(view)


def test_wrong_owner_stale_scope_and_removed_session_all_fail_closed():
    session = _session("E")
    original = dict(session.draft_counts)
    valid_action = f"{session.token}|{session.scope_nonce}"

    wrong_owner = asyncio.run(preview.cards_bulk_preview_select(
        _MenuCtx(user_id=preview.OWNER_ID + 1, values=session.scenario.target_ids),
        valid_action,
    ))
    stale_scope = asyncio.run(preview.cards_bulk_preview_select(
        _MenuCtx(values=session.scenario.target_ids),
        f"{session.token}|{session.scope_nonce + 99}",
    ))
    preview._PREVIEW_SESSIONS.pop(session.token)
    removed = asyncio.run(preview.cards_bulk_preview_select(
        _MenuCtx(values=session.scenario.target_ids), valid_action,
    ))

    for view in (wrong_owner, stale_scope, removed):
        assert "Preview expired" in _text(view)
        assert "No collection data was changed" in _text(view)
    assert session.draft_counts == original
    assert session.selected_ids == ()


def test_bulk_preview_handlers_have_no_persistence_dependency_or_write_calls():
    source = Path(preview.__file__).read_text(encoding="utf-8")
    for forbidden in (
        "MongoClient",
        "card_inventories",
        "card_trades",
        ".update_one(",
        ".update_many(",
        ".insert_one(",
        ".delete_one(",
        "_write_card_state(",
        "_write_hidden_badge_batch(",
    ):
        assert forbidden not in source

    handlers = [
        value for name, value in vars(preview).items()
        if name.startswith("cards_bulk_preview_") and inspect.iscoroutinefunction(value)
    ]
    assert handlers
    for handler in handlers:
        assert "mongo" not in inspect.signature(handler).parameters


def test_exact_screen_component_counts_stay_stable_for_phone_comparison():
    landing_session = _session("A")
    category_session = _session("A")

    workbench_session = _session("E")
    workbench_session.selected_ids = workbench_session.scenario.target_ids

    confirmation_session = _session("E")
    confirmation_session.selected_ids = confirmation_session.scenario.target_ids

    rapid_session = _session("E")
    rapid_session.selected_ids = rapid_session.scenario.target_ids
    rapid_operation = preview._begin_operation(
        rapid_session, "rapid", rapid_session.selected_ids
    )

    progress_session = _session("C")
    progress_operation = preview._begin_operation(
        progress_session, "edit_all", progress_session.editable_ids
    )
    progress_operation.next_index = 5

    review_session = _session("E")
    review_session.selected_ids = review_session.scenario.target_ids

    screens = {
        "landing": (preview._scenario_landing(landing_session), 9),
        "category": (preview._category_view(category_session), 14),
        "workbench": (preview._workbench_view(workbench_session), 21),
        "confirmation": (
            preview._bulk_confirmation_view(confirmation_session, 1), 11,
        ),
        "rapid": (preview._rapid_view(rapid_session, rapid_operation), 16),
        "progress": (
            preview._exact_progress_view(progress_session, progress_operation), 12,
        ),
        "review": (
            preview._review_view(
                review_session, review_session.selected_ids,
                title="Rapid queue review",
            ),
            11,
        ),
    }

    for name, (view, expected) in screens.items():
        assert _component_count(view) == expected, name
        _assert_payload_limits(view)
