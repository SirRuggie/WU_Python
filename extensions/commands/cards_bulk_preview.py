"""Owner-only, synthetic phone lab for bulk collection editing.

This module is intentionally separate from the production Cards editor.  Every
count lives in an expiring in-memory preview session; no inventory, reservation,
Ready state, scanner draft, or component state is written.  The controls use a
``cards_bulk_preview_*`` namespace so no posted production custom ID changes.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field

import hikari
import lightbulb

from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MessageActionRowBuilder as ActionRow,
    ModalActionRowBuilder as ModalActionRow,
    SelectOptionBuilder as SelectOption,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
    TextSelectMenuBuilder as TextSelectMenu,
)

from extensions.components import register_action
from utils import cards, troop_emoji
from utils.card_board import CATEGORY_ACCENTS
from utils.constants import GOLD_ACCENT, GREEN_ACCENT, RED_ACCENT


loader = lightbulb.Loader()

OWNER_ID = 505227988229554179
PREVIEW_TAG = "#PREVIEW"
PREVIEW_NAME = "Preview Member"
CATEGORY_ID = "elixir"
SESSION_TTL_SECONDS = 4 * 60 * 60
MAX_PREVIEW_SESSIONS = 32

ELIXIR_CARDS = tuple(cards.CATEGORY_CARDS[CATEGORY_ID])
ELIXIR_IDS = tuple(card.id for card in ELIXIR_CARDS)


@dataclass(frozen=True, slots=True)
class BulkPreviewScenario:
    key: str
    name: str
    path: str
    target_ids: tuple[str, ...]
    target_values: tuple[tuple[str, int], ...]
    reserved_ids: frozenset[str] = frozenset()
    direct_exact: bool = False

    @property
    def targets(self) -> dict[str, int]:
        return dict(self.target_values)


def _ids(*positions: int) -> tuple[str, ...]:
    return tuple(ELIXIR_IDS[position] for position in positions)


_BASE_PATTERN = (1, 1, 0, 2, 1, 3, 1, 0, 2, 4, 1, 2, 0, 1, 2, 3, 1, 0, 2)
_BASE_COUNTS = dict(zip(ELIXIR_IDS, _BASE_PATTERN, strict=True))


def _changed_targets(card_ids: tuple[str, ...], *, salt: int) -> tuple[tuple[str, int], ...]:
    result = []
    for card_id in card_ids:
        position = ELIXIR_IDS.index(card_id)
        current = _BASE_COUNTS[card_id]
        target = (position + salt) % 6
        if target == current:
            target = (target + 1) % 6
        result.append((card_id, target))
    return tuple(result)


_A_IDS = _ids(0, 4, 8, 13, 18)
_B_IDS = _ids(0, 2, 4, 6, 8, 10, 12, 14, 16, 18)
_E_IDS = _ids(0, 1, 6, 8, 11, 15, 18)
_D_TARGETS = tuple((card_id, position % 3) for position, card_id in enumerate(ELIXIR_IDS))

BULK_PREVIEW_SCENARIOS: dict[str, BulkPreviewScenario] = {
    "A": BulkPreviewScenario(
        key="A",
        name="5 scattered changed cards",
        path="Choose changed cards -> exact modal",
        target_ids=_A_IDS,
        target_values=_changed_targets(_A_IDS, salt=2),
        reserved_ids=frozenset({_ids(5)[0]}),
        direct_exact=True,
    ),
    "B": BulkPreviewScenario(
        key="B",
        name="10 scattered changed cards",
        path="Choose changed cards -> exact modal batches",
        target_ids=_B_IDS,
        target_values=_changed_targets(_B_IDS, salt=3),
        reserved_ids=frozenset({_ids(5)[0]}),
        direct_exact=True,
    ),
    "C": BulkPreviewScenario(
        key="C",
        name="All 19 exact counts",
        path="Edit all counts -> four modal batches",
        target_ids=ELIXIR_IDS,
        target_values=_changed_targets(ELIXIR_IDS, salt=4),
    ),
    "D": BulkPreviewScenario(
        key="D",
        name="19 cards split across 0 / 1 / 2",
        path="Three selected groups -> deliberate bulk confirmations",
        target_ids=ELIXIR_IDS,
        target_values=_D_TARGETS,
    ),
    "E": BulkPreviewScenario(
        key="E",
        name="Rapid correction of 7 selected cards",
        path="Choose changed cards -> rapid auto-advance queue",
        target_ids=_E_IDS,
        target_values=tuple(
            zip(_E_IDS, (2, 0, 2, 1, 2, 0, 2), strict=True)
        ),
        reserved_ids=frozenset({_ids(5)[0]}),
    ),
}


@dataclass(slots=True)
class PreviewOperation:
    token: str
    kind: str
    card_ids: tuple[str, ...]
    next_index: int = 0


@dataclass(slots=True)
class BulkPreviewSession:
    token: str
    owner_id: int
    scenario_key: str
    baseline_counts: dict[str, int]
    draft_counts: dict[str, int]
    selected_ids: tuple[str, ...] = ()
    touched_ids: set[str] = field(default_factory=set)
    scope_nonce: int = 1
    operation: PreviewOperation | None = None
    touched_at: float = field(default_factory=time.monotonic)

    @property
    def scenario(self) -> BulkPreviewScenario:
        return BULK_PREVIEW_SCENARIOS[self.scenario_key]

    @property
    def reserved_ids(self) -> frozenset[str]:
        return self.scenario.reserved_ids

    @property
    def editable_ids(self) -> tuple[str, ...]:
        return tuple(card_id for card_id in ELIXIR_IDS if card_id not in self.reserved_ids)


_PREVIEW_SESSIONS: dict[str, BulkPreviewSession] = {}


def _scenario_baseline(scenario: BulkPreviewScenario) -> dict[str, int]:
    if scenario.key == "D":
        # Every D card starts different from its 0/1/2 phone-test target.
        return {card_id: (target + 1) % 3 for card_id, target in scenario.target_values}
    return dict(_BASE_COUNTS)


def _prune_sessions(now: float | None = None) -> None:
    now = time.monotonic() if now is None else now
    expired = [
        token for token, session in _PREVIEW_SESSIONS.items()
        if now - session.touched_at > SESSION_TTL_SECONDS
    ]
    for token in expired:
        _PREVIEW_SESSIONS.pop(token, None)
    if len(_PREVIEW_SESSIONS) <= MAX_PREVIEW_SESSIONS:
        return
    oldest = sorted(_PREVIEW_SESSIONS.values(), key=lambda item: item.touched_at)
    for session in oldest[:len(_PREVIEW_SESSIONS) - MAX_PREVIEW_SESSIONS]:
        _PREVIEW_SESSIONS.pop(session.token, None)


def _new_session(owner_id: int, scenario_key: str) -> BulkPreviewSession:
    _prune_sessions()
    scenario = BULK_PREVIEW_SCENARIOS.get(scenario_key, BULK_PREVIEW_SCENARIOS["A"])
    baseline = _scenario_baseline(scenario)
    token = f"bp_{secrets.token_urlsafe(8)}"
    session = BulkPreviewSession(
        token=token,
        owner_id=int(owner_id),
        scenario_key=scenario.key,
        baseline_counts=baseline,
        draft_counts=dict(baseline),
    )
    _PREVIEW_SESSIONS[token] = session
    _prune_sessions()
    return session


def _reset_session(session: BulkPreviewSession, scenario_key: str | None = None) -> None:
    scenario = BULK_PREVIEW_SCENARIOS.get(
        scenario_key or session.scenario_key, BULK_PREVIEW_SCENARIOS["A"]
    )
    baseline = _scenario_baseline(scenario)
    session.scenario_key = scenario.key
    session.baseline_counts = baseline
    session.draft_counts = dict(baseline)
    session.selected_ids = ()
    session.touched_ids.clear()
    session.scope_nonce += 1
    session.operation = None
    session.touched_at = time.monotonic()


def _action_parts(action_id: str) -> list[str]:
    return [str(part) for part in str(action_id or "").split("|")]


def _owned_session(ctx, action_id: str) -> BulkPreviewSession | None:
    _prune_sessions()
    token = _action_parts(action_id)[0]
    session = _PREVIEW_SESSIONS.get(token)
    user_id = int(getattr(getattr(ctx, "user", None), "id", 0) or 0)
    if session is None or user_id != OWNER_ID or user_id != session.owner_id:
        return None
    session.touched_at = time.monotonic()
    return session


def _scoped_session(ctx, action_id: str) -> BulkPreviewSession | None:
    parts = _action_parts(action_id)
    session = _owned_session(ctx, action_id)
    if session is None or len(parts) < 2:
        return None
    try:
        nonce = int(parts[1])
    except (TypeError, ValueError):
        return None
    return session if nonce == session.scope_nonce else None


def _operation_session(ctx, action_id: str) -> tuple[BulkPreviewSession | None, PreviewOperation | None, list[str]]:
    parts = _action_parts(action_id)
    session = _owned_session(ctx, action_id)
    operation = session.operation if session is not None else None
    if operation is None or len(parts) < 2 or parts[1] != operation.token:
        return None, None, parts
    return session, operation, parts


def _notice(title: str, detail: str, *, error: bool = False) -> list[Container]:
    kwargs = {"accent_color": RED_ACCENT} if error else {}
    return [Container(
        components=[Text(content=f"# {title}\n{detail}")], **kwargs
    )]


def _stale_view() -> list[Container]:
    return _notice(
        "Preview expired",
        "Run `/cards-bulk-preview` again. No collection data was changed.",
        error=True,
    )


async def _modal_error(ctx) -> None:
    await ctx.respond(components=_stale_view(), ephemeral=True)


def _canonical_selected(session: BulkPreviewSession, values) -> tuple[str, ...]:
    wanted = {str(value) for value in (values or ())}
    return tuple(card_id for card_id in session.editable_ids if card_id in wanted)


def _d_next_group(session: BulkPreviewSession) -> tuple[int, tuple[str, ...]] | None:
    targets = session.scenario.targets
    for target in (0, 1, 2):
        card_ids = tuple(
            card_id for card_id in ELIXIR_IDS
            if targets.get(card_id) == target and session.draft_counts[card_id] != target
        )
        if card_ids:
            return target, card_ids
    return None


def _selection_target(session: BulkPreviewSession) -> tuple[str | None, tuple[str, ...]]:
    if session.scenario_key == "D":
        group = _d_next_group(session)
        if group is not None:
            value, card_ids = group
            return f"Set all to {value}", card_ids
    return None, session.scenario.target_ids


def _target_value(session: BulkPreviewSession, card_id: str) -> int | None:
    return session.scenario.targets.get(card_id)


def _listing(session: BulkPreviewSession) -> str:
    target_ids = set(_selection_target(session)[1])
    lines = []
    for card in ELIXIR_CARDS:
        current = session.draft_counts[card.id]
        target = _target_value(session, card.id)
        suffix = " · in a trade · locked" if card.id in session.reserved_ids else ""
        marker = " · next test group" if card.id in target_ids else ""
        target_text = f" · test -> `{target}`" if target is not None else ""
        lines.append(
            f"{troop_emoji.markup(card.id)} {card.name} · `{current}`"
            f"{target_text}{suffix}{marker}"
        )
    return "\n".join(lines)


def _scenario_measurement(session: BulkPreviewSession) -> str:
    return {
        "A": "5 checklist choices · 5 fields · 2 bot interactions · 1 modal",
        "B": (
            "10 checklist choices · 10 fields · 4 bot interactions · "
            "2 modals · 1 **Next five**"
        ),
        "C": "19 fields · 8 bot interactions · 4 modals · 3 **Next five** steps",
        "D": (
            "19 checklist choices across 3 selectors · 9 bot interactions · "
            "3 confirmations"
        ),
        "E": "7 checklist choices · 7 quick answers · 9 bot interactions · 0 modals",
    }[session.scenario_key]


def _category_view(session: BulkPreviewSession, *, note: str | None = None) -> list[Container]:
    scenario = session.scenario
    d_label, suggested_ids = _selection_target(session)
    required = len(suggested_ids)
    direct = scenario.direct_exact
    select_action = (
        "cards_bulk_preview_exact_select" if direct else "cards_bulk_preview_select"
    )
    selection_note = (
        f"Choose exactly **{required}** cards for **{d_label}**."
        if d_label
        else f"Choose the **{required}** cards marked **next test group**."
    )
    if direct:
        selection_note += " **Select** opens the first exact-count modal directly."
    elif scenario.key == "C":
        selection_note = (
            "Tap **Edit all counts** to bypass card selection and open the first five."
        )
    else:
        selection_note += " **Select** opens the selected-card workbench."
    reserved_count = len(session.reserved_ids)
    edit_all_scope = (
        f"**Edit all counts** opens all **{len(session.editable_ids)} editable cards**."
        + (
            f" The {reserved_count} reserved card stays unchanged."
            if reserved_count == 1 else
            f" The {reserved_count} reserved cards stay unchanged."
            if reserved_count else ""
        )
    )

    options = [
        SelectOption(
            label=f"{card.name} · {session.draft_counts[card.id]}"[:100],
            value=card.id,
            description=(
                f"Current {session.draft_counts[card.id]}"
                + (
                    f" · phone target {_target_value(session, card.id)}"
                    if _target_value(session, card.id) is not None else ""
                )
            )[:100],
            emoji=troop_emoji.partial(card.id),
            is_default=card.id in session.selected_ids,
        )
        for card in ELIXIR_CARDS
        if card.id not in session.reserved_ids
    ]

    body: list = [
        Text(content="# Bulk collection editor · phone preview"),
        Text(content=(
            f"**{PREVIEW_NAME}** · `{PREVIEW_TAG}`\n"
            f"**Elixir Cards** · Scenario {scenario.key}: {scenario.name}\n"
            f"-# {scenario.path}"
        )),
        Separator(divider=True),
        Text(content=(
            "ℹ️ **Preview only — nothing here is saved.**\n"
            f"{_scenario_measurement(session)}"
            + (f"\n**{note}**" if note else "")
        )),
        Text(content=_listing(session)),
        Separator(divider=True),
        Text(content=(
            f"**Choose cards to update**\n{selection_note}\n-# {edit_all_scope}"
        )),
        ActionRow(components=[TextSelectMenu(
            custom_id=f"{select_action}:{session.token}|{session.scope_nonce}",
            placeholder=(
                f"Choose {required} cards for {d_label}"
                if d_label else f"Choose {required} changed cards"
            )[:150],
            min_values=required,
            max_values=required,
            options=options,
        )]),
        ActionRow(components=[
            Button(
                style=(
                    hikari.ButtonStyle.PRIMARY
                    if scenario.key == "C" else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_bulk_preview_edit_all:{session.token}|{session.scope_nonce}",
                label="Edit all counts",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_change_scenario:{session.token}",
                label="Scenarios",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_cancel:{session.token}",
                label="Cancel",
            ),
        ]),
    ]
    return [Container(
        accent_color=CATEGORY_ACCENTS[CATEGORY_ID], components=body
    )]


def _selected_lines(session: BulkPreviewSession) -> str:
    return "\n".join(
        f"{troop_emoji.markup(card_id)} {cards.CARD_BY_ID[card_id].name} · "
        f"`{session.draft_counts[card_id]}`"
        for card_id in session.selected_ids
    )


def _workbench_view(
    session: BulkPreviewSession, *, note: str | None = None
) -> list[Container]:
    count = len(session.selected_ids)
    d_group = _d_next_group(session) if session.scenario_key == "D" else None
    recommended_bulk = d_group[0] if d_group is not None else None
    phone_path = (
        f"Phone-test target: Set all {count} selected cards to {recommended_bulk}."
        if recommended_bulk is not None else
        "Phone-test path: Tap Review one at a time, then answer each card."
        if session.scenario_key == "E" else
        "Phone-test path: Different counts opens exact-count batches."
    )
    return [Container(accent_color=CATEGORY_ACCENTS[CATEGORY_ID], components=[
        Text(content="# Selected-card workbench · preview"),
        Text(content=(
            f"**{PREVIEW_NAME}** · `{PREVIEW_TAG}`\n"
            f"**Elixir Cards** · **{count} selected cards**"
        )),
        Separator(divider=True),
        Text(content=_selected_lines(session)),
        Separator(divider=True),
        Text(content=(
            f"⚠️ **ALL {count} SELECTED CARDS**\n"
            "Every bulk button below applies to the complete list above.\n"
            f"**{phone_path}**"
            + (f"\n**{note}**" if note else "")
        )),
        ActionRow(components=[
            Button(
                style=(
                    hikari.ButtonStyle.SECONDARY
                    if session.scenario_key in {"D", "E"}
                    else hikari.ButtonStyle.PRIMARY
                ),
                custom_id=f"cards_bulk_preview_exact_open:{session.token}|{session.scope_nonce}",
                label="Different counts",
            ),
            Button(
                style=(
                    hikari.ButtonStyle.PRIMARY
                    if session.scenario_key == "E"
                    else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_bulk_preview_rapid_start:{session.token}|{session.scope_nonce}",
                label="Review one at a time",
            ),
        ]),
        Text(content="**Set every selected card to:**"),
        ActionRow(components=[
            Button(
                style=(
                    hikari.ButtonStyle.PRIMARY
                    if recommended_bulk == 0 else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_bulk_preview_bulk_choice:{session.token}|{session.scope_nonce}|0",
                label="0",
            ),
            Button(
                style=(
                    hikari.ButtonStyle.PRIMARY
                    if recommended_bulk == 1 else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_bulk_preview_bulk_choice:{session.token}|{session.scope_nonce}|1",
                label="1",
            ),
            Button(
                style=(
                    hikari.ButtonStyle.PRIMARY
                    if recommended_bulk == 2 else hikari.ButtonStyle.SECONDARY
                ),
                custom_id=f"cards_bulk_preview_bulk_choice:{session.token}|{session.scope_nonce}|2",
                label="2",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_other:{session.token}|{session.scope_nonce}",
                label="Other",
            ),
        ]),
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_change_selection:{session.token}|{session.scope_nonce}",
                label="Change selection",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_cancel:{session.token}",
                label="Cancel",
            ),
        ]),
        Text(content="-# Synthetic draft only · no inventory or trade state changes."),
    ])]


def _begin_operation(session: BulkPreviewSession, kind: str, card_ids: tuple[str, ...]) -> PreviewOperation:
    operation = PreviewOperation(
        token=secrets.token_urlsafe(4),
        kind=kind,
        card_ids=tuple(card_ids),
    )
    session.operation = operation
    return operation


def _exact_modal_payload(
    session: BulkPreviewSession, operation: PreviewOperation, start: int
) -> dict:
    batch = operation.card_ids[start:start + 5]
    end = start + len(batch)
    inputs = []
    for offset, card_id in enumerate(batch):
        card = cards.CARD_BY_ID[card_id]
        target = _target_value(session, card_id)
        target_text = f" · test {target}" if target is not None else ""
        inputs.append(ModalActionRow().add_text_input(
            f"q{offset}",
            f"{card.name}{target_text}"[:45],
            value=str(session.draft_counts[card_id]),
            placeholder=f"0 to {cards.MAX_COPIES}",
            min_length=1,
            max_length=2,
            required=True,
        ))
    return {
        "title": f"Preview counts · {start + 1}-{end} of {len(operation.card_ids)}"[:45],
        "custom_id": (
            f"cards_bulk_preview_exact_submit:{session.token}|{operation.token}|{start}"
        ),
        "components": inputs,
    }


async def _open_exact_modal(
    ctx, session: BulkPreviewSession, operation: PreviewOperation, start: int
) -> None:
    await ctx.respond_with_modal(**_exact_modal_payload(session, operation, start))


def _exact_progress_view(
    session: BulkPreviewSession,
    operation: PreviewOperation,
    *,
    error: str | None = None,
) -> list[Container]:
    done = operation.next_index
    remaining = len(operation.card_ids) - done
    listing = "\n".join(
        f"{'✓' if index < done else '○'} {cards.CARD_BY_ID[card_id].name} · "
        f"`{session.draft_counts[card_id]}`"
        for index, card_id in enumerate(operation.card_ids)
    )
    next_label = "Retry this five" if error else "Next five"
    next_index = done
    return [Container(accent_color=CATEGORY_ACCENTS[CATEGORY_ID], components=[
        Text(content="# Exact-count batches · preview"),
        Text(content=(
            f"**{PREVIEW_NAME}** · `{PREVIEW_TAG}`\n"
            f"**Elixir Cards** · **{done} of {len(operation.card_ids)} staged**"
        )),
        Text(content=(
            f"⚠️ This scope is all **{len(operation.card_ids)} cards** in this exact-count run.\n"
            f"{remaining} remain. Discord cannot open the next modal from a modal submit."
            + (f"\n**{error}**" if error else "")
        )),
        Separator(divider=True),
        Text(content=listing),
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=(
                    f"cards_bulk_preview_exact_next:{session.token}|"
                    f"{operation.token}|{next_index}"
                ),
                label=next_label,
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_change_selection:{session.token}|{session.scope_nonce}",
                label="Change selection",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_cancel:{session.token}",
                label="Cancel",
            ),
        ]),
        Text(content="-# Preview only · the staged answers exist only in memory."),
    ])]


def _bulk_confirmation_view(session: BulkPreviewSession, target: int) -> list[Container]:
    count = len(session.selected_ids)
    names = "\n".join(
        f"{troop_emoji.markup(card_id)} {cards.CARD_BY_ID[card_id].name} · "
        f"`{session.draft_counts[card_id]}` -> `{target}`"
        for card_id in session.selected_ids
    )
    return [Container(accent_color=GOLD_ACCENT, components=[
        Text(content="# Confirm bulk preview"),
        Text(content=(
            f"**{PREVIEW_NAME}** · `{PREVIEW_TAG}`\n"
            f"**Elixir Cards** · **{count} selected cards**"
        )),
        Separator(divider=True),
        Text(content=f"⚠️ **Set all {count} to {target}?**\nThis means every card below."),
        Text(content=names),
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SUCCESS,
                custom_id=(
                    f"cards_bulk_preview_bulk_apply:{session.token}|"
                    f"{session.scope_nonce}|{target}"
                ),
                label=f"Set all to {target}",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_bulk_back:{session.token}|{session.scope_nonce}",
                label="Back",
            ),
        ]),
        Text(content="-# Confirmation changes only this synthetic preview draft."),
    ])]


def _rapid_view(
    session: BulkPreviewSession,
    operation: PreviewOperation,
    *,
    error: str | None = None,
) -> list[Container]:
    index = operation.next_index
    card_id = operation.card_ids[index]
    card = cards.CARD_BY_ID[card_id]
    current = session.draft_counts[card_id]
    target = _target_value(session, card_id)
    return [Container(accent_color=CATEGORY_ACCENTS[CATEGORY_ID], components=[
        Text(content=f"# {index + 1} of {len(operation.card_ids)} · {card.name}"),
        Text(content=(
            f"**{PREVIEW_NAME}** · `{PREVIEW_TAG}`\n"
            f"**Elixir Cards** · rapid review"
        )),
        Separator(divider=True),
        Text(content=(
            f"**Current: {current}**"
            + (f"\n-# Scenario phone-test target: {target}" if target is not None else "")
            + (f"\n**{error}**" if error else "")
        )),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=(
                    f"cards_bulk_preview_rapid_set:{session.token}|"
                    f"{operation.token}|{index}|0"
                ),
                label="Set 0",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=(
                    f"cards_bulk_preview_rapid_set:{session.token}|"
                    f"{operation.token}|{index}|1"
                ),
                label="Set 1",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=(
                    f"cards_bulk_preview_rapid_set:{session.token}|"
                    f"{operation.token}|{index}|2"
                ),
                label="Set 2",
            ),
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=(
                    f"cards_bulk_preview_rapid_number:{session.token}|"
                    f"{operation.token}|{index}"
                ),
                label="Set number",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=(
                    f"cards_bulk_preview_rapid_skip:{session.token}|"
                    f"{operation.token}|{index}"
                ),
                label="Skip",
            ),
        ]),
        Text(content="-# An answer advances automatically to the next selected card."),
        Separator(divider=True),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_change_selection:{session.token}|{session.scope_nonce}",
                label="Change selection",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_cancel:{session.token}",
                label="Cancel",
            ),
        ]),
    ])]


def _review_view(
    session: BulkPreviewSession,
    card_ids: tuple[str, ...],
    *,
    title: str = "Preview review",
) -> list[Container]:
    lines = []
    changed = 0
    for card_id in card_ids:
        before = session.baseline_counts[card_id]
        after = session.draft_counts[card_id]
        changed += before != after
        marker = "changed" if before != after else "unchanged"
        lines.append(
            f"{troop_emoji.markup(card_id)} {cards.CARD_BY_ID[card_id].name} · "
            f"`{before}` -> `{after}` · {marker}"
        )
    return [Container(accent_color=GREEN_ACCENT, components=[
        Text(content=f"# {title} · nothing saved"),
        Text(content=(
            f"**{PREVIEW_NAME}** · `{PREVIEW_TAG}`\n"
            f"**Elixir Cards** · **{len(card_ids)} reviewed · {changed} changed**"
        )),
        Separator(divider=True),
        Text(content="\n".join(lines) or "No cards were changed in this preview."),
        Separator(divider=True),
        Text(content=(
            "✅ **Sandbox complete**\n"
            "No database, inventory, reservation, Ready state, or scanner data changed."
        )),
        ActionRow(components=[
            Button(
                style=hikari.ButtonStyle.PRIMARY,
                custom_id=f"cards_bulk_preview_restart:{session.token}",
                label="Restart scenario",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_change_scenario:{session.token}",
                label="Change scenario",
            ),
            Button(
                style=hikari.ButtonStyle.SECONDARY,
                custom_id=f"cards_bulk_preview_cancel:{session.token}",
                label="Close preview",
            ),
        ]),
    ])]


def _scenario_landing(session: BulkPreviewSession) -> list[Container]:
    return [Container(components=[
        Text(content="# Bulk collection editor · phone preview"),
        Text(content=(
            "Choose a synthetic scenario. Every path is preview only and expires from memory.\n"
            "-# A/B: select directly to exact modal · C: edit all · D: bulk state · E: rapid queue"
        )),
        Separator(divider=True),
        ActionRow(components=[TextSelectMenu(
            custom_id=f"cards_bulk_preview_scenario:{session.token}",
            placeholder="Choose a phone-test scenario",
            min_values=1,
            max_values=1,
            options=[
                SelectOption(
                    label=f"{scenario.key} · {scenario.name}"[:100],
                    value=scenario.key,
                    description=scenario.path[:100],
                )
                for scenario in BULK_PREVIEW_SCENARIOS.values()
            ],
        )]),
        ActionRow(components=[Button(
            style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"cards_bulk_preview_cancel:{session.token}",
            label="Close preview",
        )]),
        Text(content="-# Synthetic account · no production collection is loaded."),
    ])]


def _closed_view() -> list[Container]:
    return [Container(components=[Text(content=(
        "# Preview closed\n"
        "Nothing was saved. Run `/cards-bulk-preview` whenever you want another phone test."
    ))])]


def _modal_text_value(ctx, custom_id: str) -> str:
    for row in getattr(ctx.interaction, "components", ()) or ():
        for component in row:
            if getattr(component, "custom_id", None) == custom_id:
                return str(getattr(component, "value", "") or "").strip()
    return ""


def _parsed_count(raw: object) -> int | None:
    if isinstance(raw, bool):
        return None
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return None
    return value if 0 <= value <= cards.MAX_COPIES else None


async def _ack_modal_and_edit(ctx, components) -> None:
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(
            hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
        )
    else:
        await ctx.defer(ephemeral=True)
    await ctx.interaction.edit_initial_response(components=components)


def _selected_from_interaction(session: BulkPreviewSession, ctx) -> tuple[str, ...]:
    return _canonical_selected(
        session, getattr(getattr(ctx, "interaction", None), "values", ()) or ()
    )


def _selection_problem(session: BulkPreviewSession, selected: tuple[str, ...]) -> str | None:
    _label, suggested = _selection_target(session)
    required = len(suggested)
    if len(selected) != required:
        return f"Choose exactly {required} editable cards. Reserved cards stay locked."
    return None


@loader.command
class CardsBulkPreview(
    lightbulb.SlashCommand,
    name="cards-bulk-preview",
    description="Try synthetic bulk collection editors on a phone (owner only)",
):
    scenario = lightbulb.string(
        "scenario",
        "Which synthetic phone test to open",
        default="A",
        choices=[
            lightbulb.Choice(f"{item.key} · {item.name}", item.key)
            for item in BULK_PREVIEW_SCENARIOS.values()
        ],
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context) -> None:
        if int(ctx.user.id) != OWNER_ID:
            await ctx.respond(
                components=_notice("Owner only", "This preview command is owner only.", error=True),
                flags=(
                    hikari.MessageFlag.IS_COMPONENTS_V2
                    | hikari.MessageFlag.EPHEMERAL
                ),
            )
            return
        session = _new_session(int(ctx.user.id), self.scenario)
        await ctx.respond(
            components=_category_view(session),
            flags=(
                hikari.MessageFlag.IS_COMPONENTS_V2
                | hikari.MessageFlag.EPHEMERAL
            ),
        )


@register_action("cards_bulk_preview_scenario")
async def cards_bulk_preview_scenario(ctx, action_id: str, **_kwargs):
    session = _owned_session(ctx, action_id)
    if session is None:
        return _stale_view()
    values = list(getattr(ctx.interaction, "values", ()) or ())
    scenario_key = str(values[0]) if values else ""
    if scenario_key not in BULK_PREVIEW_SCENARIOS:
        return _scenario_landing(session)
    _reset_session(session, scenario_key)
    return _category_view(session)


@register_action("cards_bulk_preview_select")
async def cards_bulk_preview_select(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None:
        return _stale_view()
    selected = _selected_from_interaction(session, ctx)
    problem = _selection_problem(session, selected)
    if problem:
        return _category_view(session, note=problem)
    session.selected_ids = selected
    session.scope_nonce += 1
    session.operation = None
    return _workbench_view(session)


@register_action(
    "cards_bulk_preview_exact_select", opens_modal=True, no_return=True
)
async def cards_bulk_preview_exact_select(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None:
        await _modal_error(ctx)
        return
    selected = _selected_from_interaction(session, ctx)
    problem = _selection_problem(session, selected)
    if problem:
        await ctx.respond(
            components=_category_view(session, note=problem), edit=True
        )
        return
    session.selected_ids = selected
    session.scope_nonce += 1
    operation = _begin_operation(session, "selected_exact", selected)
    await _open_exact_modal(ctx, session, operation, 0)


@register_action("cards_bulk_preview_edit_all", opens_modal=True, no_return=True)
async def cards_bulk_preview_edit_all(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None:
        await _modal_error(ctx)
        return
    operation = _begin_operation(session, "edit_all", session.editable_ids)
    await _open_exact_modal(ctx, session, operation, 0)


@register_action("cards_bulk_preview_exact_open", opens_modal=True, no_return=True)
async def cards_bulk_preview_exact_open(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None or not session.selected_ids:
        await _modal_error(ctx)
        return
    operation = _begin_operation(session, "selected_exact", session.selected_ids)
    await _open_exact_modal(ctx, session, operation, 0)


@register_action("cards_bulk_preview_exact_next", opens_modal=True, no_return=True)
async def cards_bulk_preview_exact_next(ctx, action_id: str, **_kwargs):
    session, operation, parts = _operation_session(ctx, action_id)
    if session is None or operation is None or len(parts) < 3:
        await _modal_error(ctx)
        return
    try:
        start = int(parts[2])
    except (TypeError, ValueError):
        await _modal_error(ctx)
        return
    if start != operation.next_index or start >= len(operation.card_ids):
        await _modal_error(ctx)
        return
    await _open_exact_modal(ctx, session, operation, start)


@register_action(
    "cards_bulk_preview_exact_submit", is_modal=True, no_return=True
)
async def cards_bulk_preview_exact_submit(ctx, action_id: str, **_kwargs):
    session, operation, parts = _operation_session(ctx, action_id)
    if session is None or operation is None or len(parts) < 3:
        await _ack_modal_and_edit(ctx, _stale_view())
        return
    try:
        start = int(parts[2])
    except (TypeError, ValueError):
        await _ack_modal_and_edit(ctx, _stale_view())
        return
    if start != operation.next_index or start >= len(operation.card_ids):
        await _ack_modal_and_edit(ctx, _stale_view())
        return

    batch = operation.card_ids[start:start + 5]
    parsed = [_parsed_count(_modal_text_value(ctx, f"q{offset}")) for offset in range(len(batch))]
    if any(value is None for value in parsed):
        await _ack_modal_and_edit(
            ctx,
            _exact_progress_view(
                session,
                operation,
                error=f"Use a whole number from 0 to {cards.MAX_COPIES} in every field.",
            ),
        )
        return

    # Validate the entire five-card batch before changing the synthetic draft.
    for card_id, target in zip(batch, parsed, strict=True):
        session.draft_counts[card_id] = int(target)
        session.touched_ids.add(card_id)
    operation.next_index += len(batch)

    if operation.next_index < len(operation.card_ids):
        view = _exact_progress_view(session, operation)
    else:
        view = _review_view(
            session,
            operation.card_ids,
            title=(
                "Edit all counts review"
                if operation.kind == "edit_all" else "Selected exact-count review"
            ),
        )
    await _ack_modal_and_edit(ctx, view)


@register_action("cards_bulk_preview_bulk_choice")
async def cards_bulk_preview_bulk_choice(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    parts = _action_parts(action_id)
    if session is None or not session.selected_ids or len(parts) < 3:
        return _stale_view()
    target = _parsed_count(parts[2])
    if target not in (0, 1, 2):
        return _workbench_view(session)
    return _bulk_confirmation_view(session, target)


def _other_modal_payload(session: BulkPreviewSession) -> dict:
    return {
        "title": f"Set all {len(session.selected_ids)} · preview"[:45],
        "custom_id": (
            f"cards_bulk_preview_other_submit:{session.token}|{session.scope_nonce}"
        ),
        "components": [ModalActionRow().add_text_input(
            "copies",
            "How many for every selected card?",
            placeholder=f"0 to {cards.MAX_COPIES}",
            min_length=1,
            max_length=2,
            required=True,
        )],
    }


@register_action("cards_bulk_preview_other", opens_modal=True, no_return=True)
async def cards_bulk_preview_other(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None or not session.selected_ids:
        await _modal_error(ctx)
        return
    await ctx.respond_with_modal(**_other_modal_payload(session))


@register_action(
    "cards_bulk_preview_other_submit", is_modal=True, no_return=True
)
async def cards_bulk_preview_other_submit(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None or not session.selected_ids:
        await _ack_modal_and_edit(ctx, _stale_view())
        return
    target = _parsed_count(_modal_text_value(ctx, "copies"))
    if target is None:
        view = _workbench_view(
            session,
            note=f"Use a whole number from 0 to {cards.MAX_COPIES}.",
        )
    else:
        view = _bulk_confirmation_view(session, target)
    await _ack_modal_and_edit(ctx, view)


@register_action("cards_bulk_preview_bulk_apply")
async def cards_bulk_preview_bulk_apply(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    parts = _action_parts(action_id)
    if session is None or not session.selected_ids or len(parts) < 3:
        return _stale_view()
    target = _parsed_count(parts[2])
    if target is None:
        return _workbench_view(session)
    selected = session.selected_ids
    for card_id in selected:
        session.draft_counts[card_id] = target
        session.touched_ids.add(card_id)

    if session.scenario_key == "D":
        session.selected_ids = ()
        session.operation = None
        session.scope_nonce += 1
        if _d_next_group(session) is not None:
            return _category_view(
                session,
                note=(
                    f"Preview staged {len(selected)} cards at {target}. "
                    "Choose the next marked group."
                ),
            )
        return _review_view(
            session, ELIXIR_IDS, title="0 / 1 / 2 bulk-state review"
        )
    return _review_view(session, selected, title="Same-value bulk review")


@register_action("cards_bulk_preview_bulk_back")
async def cards_bulk_preview_bulk_back(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None or not session.selected_ids:
        return _stale_view()
    return _workbench_view(session)


@register_action("cards_bulk_preview_rapid_start")
async def cards_bulk_preview_rapid_start(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None or not session.selected_ids:
        return _stale_view()
    operation = _begin_operation(session, "rapid", session.selected_ids)
    return _rapid_view(session, operation)


def _advance_rapid(
    session: BulkPreviewSession,
    operation: PreviewOperation,
    *,
    target: int | None,
) -> list[Container]:
    card_id = operation.card_ids[operation.next_index]
    if target is not None:
        session.draft_counts[card_id] = target
        session.touched_ids.add(card_id)
    operation.next_index += 1
    if operation.next_index >= len(operation.card_ids):
        return _review_view(session, operation.card_ids, title="Rapid queue review")
    return _rapid_view(session, operation)


def _rapid_action(
    ctx, action_id: str, *, with_target: bool
) -> tuple[BulkPreviewSession | None, PreviewOperation | None, int | None]:
    session, operation, parts = _operation_session(ctx, action_id)
    if session is None or operation is None or operation.kind != "rapid" or len(parts) < 3:
        return None, None, None
    try:
        index = int(parts[2])
    except (TypeError, ValueError):
        return None, None, None
    if index != operation.next_index or index >= len(operation.card_ids):
        return None, None, None
    if not with_target:
        return session, operation, None
    if len(parts) < 4:
        return None, None, None
    target = _parsed_count(parts[3])
    if target not in (0, 1, 2):
        return None, None, None
    return session, operation, target


@register_action("cards_bulk_preview_rapid_set")
async def cards_bulk_preview_rapid_set(ctx, action_id: str, **_kwargs):
    session, operation, target = _rapid_action(ctx, action_id, with_target=True)
    if session is None or operation is None or target is None:
        return _stale_view()
    return _advance_rapid(session, operation, target=target)


@register_action("cards_bulk_preview_rapid_skip")
async def cards_bulk_preview_rapid_skip(ctx, action_id: str, **_kwargs):
    session, operation, _target = _rapid_action(ctx, action_id, with_target=False)
    if session is None or operation is None:
        return _stale_view()
    return _advance_rapid(session, operation, target=None)


def _rapid_number_modal_payload(
    session: BulkPreviewSession, operation: PreviewOperation
) -> dict:
    index = operation.next_index
    card_id = operation.card_ids[index]
    card = cards.CARD_BY_ID[card_id]
    return {
        "title": f"Preview · {card.name}"[:45],
        "custom_id": (
            f"cards_bulk_preview_rapid_number_submit:{session.token}|"
            f"{operation.token}|{index}"
        ),
        "components": [ModalActionRow().add_text_input(
            "copies",
            "How many do you have?",
            value=str(session.draft_counts[card_id]),
            placeholder=f"0 to {cards.MAX_COPIES}",
            min_length=1,
            max_length=2,
            required=True,
        )],
    }


@register_action("cards_bulk_preview_rapid_number", opens_modal=True, no_return=True)
async def cards_bulk_preview_rapid_number(ctx, action_id: str, **_kwargs):
    session, operation, _target = _rapid_action(ctx, action_id, with_target=False)
    if session is None or operation is None:
        await _modal_error(ctx)
        return
    await ctx.respond_with_modal(**_rapid_number_modal_payload(session, operation))


@register_action(
    "cards_bulk_preview_rapid_number_submit", is_modal=True, no_return=True
)
async def cards_bulk_preview_rapid_number_submit(ctx, action_id: str, **_kwargs):
    session, operation, _target = _rapid_action(ctx, action_id, with_target=False)
    if session is None or operation is None:
        await _ack_modal_and_edit(ctx, _stale_view())
        return
    target = _parsed_count(_modal_text_value(ctx, "copies"))
    view = (
        _rapid_view(
            session,
            operation,
            error=f"Use a whole number from 0 to {cards.MAX_COPIES}.",
        )
        if target is None
        else _advance_rapid(session, operation, target=target)
    )
    await _ack_modal_and_edit(ctx, view)


@register_action("cards_bulk_preview_change_selection")
async def cards_bulk_preview_change_selection(ctx, action_id: str, **_kwargs):
    session = _scoped_session(ctx, action_id)
    if session is None:
        return _stale_view()
    session.operation = None
    session.scope_nonce += 1
    return _category_view(
        session,
        note=(
            "Selection reopened. Staged preview values remain; nothing real was saved."
        ),
    )


@register_action("cards_bulk_preview_change_scenario")
async def cards_bulk_preview_change_scenario(ctx, action_id: str, **_kwargs):
    session = _owned_session(ctx, action_id)
    if session is None:
        return _stale_view()
    session.operation = None
    session.selected_ids = ()
    session.scope_nonce += 1
    return _scenario_landing(session)


@register_action("cards_bulk_preview_restart")
async def cards_bulk_preview_restart(ctx, action_id: str, **_kwargs):
    session = _owned_session(ctx, action_id)
    if session is None:
        return _stale_view()
    _reset_session(session)
    return _category_view(session)


@register_action("cards_bulk_preview_cancel")
async def cards_bulk_preview_cancel(ctx, action_id: str, **_kwargs):
    session = _owned_session(ctx, action_id)
    if session is None:
        return _stale_view()
    _PREVIEW_SESSIONS.pop(session.token, None)
    return _closed_view()
