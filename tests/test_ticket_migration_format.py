import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from extensions.commands.tickets import legacy_migration as migration


NOW = datetime(2025, 6, 7, 8, 9, 10, tzinfo=timezone.utc)


def _message(message_id=3, content="hello", timestamp=NOW):
    return SimpleNamespace(
        id=message_id,
        content=content,
        timestamp=timestamp,
        author=SimpleNamespace(
            id=4, username="Applicant", display_name="Applicant",
            display_avatar_url=None,
        ),
        attachments=[], embeds=[], user_mentions={},
    )


def test_hidden_marker_round_trip_is_invisible_and_ignores_malformed_runs():
    marker = "migration-source:1:2:3:1/1"
    encoded = migration._hidden_marker(marker)

    assert marker not in encoded
    assert set(encoded) <= {
        migration._HIDDEN_MARKER_DELIMITER,
        migration._HIDDEN_MARKER_ZERO,
        migration._HIDDEN_MARKER_ONE,
    }
    assert migration._hidden_markers(f"message\n{encoded}") == {marker}
    assert migration._hidden_markers(
        migration._HIDDEN_MARKER_DELIMITER
        + migration._HIDDEN_MARKER_ZERO
        + migration._HIDDEN_MARKER_DELIMITER
    ) == set()


def test_clone_parts_fit_discord_without_visible_source_or_per_message_time():
    parts = migration._message_parts(
        content="x" * 5000,
        source_guild_id=123456789012345678,
        source_channel_id=223456789012345678,
        source_message_id=323456789012345678,
        timestamp=NOW,
    )

    assert len(parts) > 1
    for marker, content in parts:
        assert len(content) <= migration.DISCORD_MESSAGE_CONTENT_LIMIT
        assert marker in migration._hidden_markers(content)
        assert "migration-source" not in content
        assert "Originally sent" not in content
        assert "Continued from original" not in content
        assert "2025-06-07" not in content


def test_boundary_send_is_exactly_once_and_uses_neutral_timeline_author(monkeypatch):
    calls = []

    async def execute(_rest, _webhook, content, **kwargs):
        calls.append((content, kwargs))

    monkeypatch.setattr(migration, "_execute_paced_webhook", execute)
    known = set()
    state = {"_id": "legacy:1:2"}
    kwargs = dict(
        rest=SimpleNamespace(), webhook=SimpleNamespace(id=8, token="token"),
        thread_id=9, state=state, space="public", kind="start",
        message=_message(), known_markers=known,
    )

    asyncio.run(migration._copy_boundary(**kwargs))
    asyncio.run(migration._copy_boundary(**kwargs))

    assert len(calls) == 1
    content, webhook_kwargs = calls[0]
    assert content.startswith("Ticket started: <t:1749283750:F>")
    assert "migration-boundary" not in content
    assert webhook_kwargs["username"] == "Ticket history"
    assert "migration-boundary:legacy:1:2:public:start" in known


def test_copy_space_orders_boundaries_around_messages_and_does_not_checkpoint_on_start_error(
    monkeypatch,
):
    state = {
        "_id": "legacy:1:2", "source": {"guild_id": 1},
        "progress": {"public": {"copied": 0, "losses": []}},
    }
    events = []

    async def all_messages(_rest, _channel_id):
        return [_message(10), _message(11)]

    async def no_markers(_rest, _thread_id):
        return set()

    async def clone(**kwargs):
        events.append(kwargs["marker"])
        kwargs["known_markers"].add(kwargs["marker"])
        return []

    async def update(_mongo, _migration_id, _owner, fields):
        events.append(("checkpoint", fields["progress.public.last_source_message_id"]))
        return state

    monkeypatch.setattr(migration, "_all_messages", all_messages)
    monkeypatch.setattr(migration, "_destination_markers", no_markers)
    monkeypatch.setattr(migration, "_execute_clone_part", clone)
    monkeypatch.setattr(migration, "_migration_update", update)

    asyncio.run(migration._copy_space(
        bot=SimpleNamespace(rest=SimpleNamespace()), mongo=SimpleNamespace(),
        state=state, owner="owner", space="public", source_channel_id=2,
        destination_thread_id=9, webhook=SimpleNamespace(), role_names={}, channel_names={},
    ))

    assert events[0].endswith(":public:start")
    assert events[1].startswith("migration-source:1:2:10:")
    assert events[2] == ("checkpoint", 10)
    assert events[3].startswith("migration-source:1:2:11:")
    assert events[4] == ("checkpoint", 11)
    assert events[5].endswith(":public:end")

    events.clear()

    async def fail_start(**kwargs):
        events.append(kwargs["marker"])
        raise TimeoutError("boundary response unavailable")

    monkeypatch.setattr(migration, "_execute_clone_part", fail_start)
    try:
        asyncio.run(migration._copy_space(
            bot=SimpleNamespace(rest=SimpleNamespace()), mongo=SimpleNamespace(),
            state=state, owner="owner", space="public", source_channel_id=2,
            destination_thread_id=9, webhook=SimpleNamespace(), role_names={}, channel_names={},
        ))
    except TimeoutError:
        pass
    else:
        raise AssertionError("boundary failure must stop before message checkpoints")
    assert events == ["migration-boundary:legacy:1:2:public:start"]
