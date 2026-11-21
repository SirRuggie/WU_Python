"""Ticket rollout read model and public read owner shared by HTTP and bot adapters.

The runtime retains all writes, indexes, slots and claims. One parser is reexported
there so old callers retain exact object and validation semantics.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

ROLLOUT_ID = "ticket-runtime"
ROLLOUT_SCHEMA_VERSION = 1

PHASE_LEGACY_ONLY = "legacy_only"
PHASE_PREPARED = "prepared"
PHASE_PILOT = "pilot"
PHASE_THREAD_DEFAULT = "thread_default"
PHASE_ROLLBACK_LEGACY = "rollback_legacy"
PHASE_THREAD_ONLY = "thread_only"
VALID_PHASES = frozenset(
    {
        PHASE_LEGACY_ONLY,
        PHASE_PREPARED,
        PHASE_PILOT,
        PHASE_THREAD_DEFAULT,
        PHASE_ROLLBACK_LEGACY,
        PHASE_THREAD_ONLY,
    }
)


_VALID_TICKET_TYPES = frozenset({"main", "fwa", "account", "staff"})


@dataclass(frozen=True, slots=True)
class IntakeSource:
    guild_id: int
    channel_id: int
    message_id: int

    def matches(self, *, guild_id: int, channel_id: int, message_id: int) -> bool:
        return (
            self.guild_id == int(guild_id)
            and self.channel_id == int(channel_id)
            and self.message_id == int(message_id)
        )


@dataclass(frozen=True, slots=True)
class RolloutState:
    phase: str
    revision: int
    valid: bool
    legacy_intake: IntakeSource | None = None
    thread_intake: IntakeSource | None = None
    pilot_intake: IntakeSource | None = None
    pilot_user_ids: tuple[int, ...] = ()
    pilot_role_ids: tuple[int, ...] = ()
    pilot_ticket_types: tuple[str, ...] = ("main", "fwa")
    desk_intake: IntakeSource | None = None


def _positive_int(value: Any) -> int | None:
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _intake_source(value: Any) -> IntakeSource | None:
    if not isinstance(value, Mapping):
        return None
    guild_id = _positive_int(value.get("guild_id"))
    channel_id = _positive_int(value.get("channel_id"))
    message_id = _positive_int(value.get("message_id"))
    if guild_id is None or channel_id is None or message_id is None:
        return None
    return IntakeSource(guild_id, channel_id, message_id)


def _id_tuple(values: Any) -> tuple[int, ...]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        return ()
    return tuple(sorted({item for value in values if (item := _positive_int(value))}))


def parse_rollout(document: Mapping[str, Any] | None) -> RolloutState:
    if not document:
        return RolloutState(PHASE_LEGACY_ONLY, 0, False)
    phase = document.get("phase")
    revision = document.get("revision")
    if (
        document.get("schema_version") != ROLLOUT_SCHEMA_VERSION
        or phase not in VALID_PHASES
        or not isinstance(revision, int)
        or isinstance(revision, bool)
        or revision < 0
    ):
        return RolloutState(PHASE_LEGACY_ONLY, 0, False)
    pilot = document.get("pilot") if isinstance(document.get("pilot"), Mapping) else {}
    ticket_types = pilot.get("ticket_types", ("main", "fwa"))
    if not isinstance(ticket_types, Sequence) or isinstance(ticket_types, (str, bytes)):
        ticket_types = ()
    normalized_types = tuple(
        sorted({str(item).strip().lower() for item in ticket_types} & _VALID_TICKET_TYPES)
    )
    legacy_intake = _intake_source(document.get("legacy_intake"))
    thread_intake = _intake_source(document.get("thread_intake"))
    pilot_intake = _intake_source(pilot.get("intake"))
    desk_intake = _intake_source(document.get("desk_intake"))
    pilot_user_ids = _id_tuple(pilot.get("user_ids"))
    pilot_role_ids = _id_tuple(pilot.get("role_ids"))
    if (
        legacy_intake is None
        or thread_intake is None
        or pilot_intake is None
        or legacy_intake.guild_id == thread_intake.guild_id
        or thread_intake.guild_id != pilot_intake.guild_id
        or thread_intake.channel_id == pilot_intake.channel_id
        or not normalized_types
        or (not pilot_user_ids and not pilot_role_ids)
    ):
        return RolloutState(PHASE_LEGACY_ONLY, 0, False)
    return RolloutState(
        phase=phase,
        revision=revision,
        valid=True,
        legacy_intake=legacy_intake,
        thread_intake=thread_intake,
        pilot_intake=pilot_intake,
        pilot_user_ids=pilot_user_ids,
        pilot_role_ids=pilot_role_ids,
        pilot_ticket_types=normalized_types,
        desk_intake=desk_intake,
    )


async def get_rollout(mongo: Any) -> RolloutState:
    return parse_rollout(await mongo.ticket_rollout.find_one({"_id": ROLLOUT_ID}))
