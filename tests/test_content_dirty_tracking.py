import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import hikari

from extensions.commands import content, manage


def run(coro):
    return asyncio.run(coro)


def context(values=("about-us",)):
    return SimpleNamespace(
        user=SimpleNamespace(id=1),
        interaction=SimpleNamespace(
            guild_id=2, values=values,
            member=SimpleNamespace(permissions=hikari.Permissions.MANAGE_GUILD),
        ),
    )


def test_document_open_records_saved_copy_and_clean_back_skips_warning(monkeypatch):
    root = {"_id": "root", "user_id": 1, "guild_id": 2,
            "view": "root", "manage_token": "home-token"}
    monkeypatch.setattr(content, "load", AsyncMock(return_value=(root, None)))
    monkeypatch.setattr(content, "new_draft", AsyncMock(side_effect=lambda _db, row: dict(row, _id="opened")))
    db = SimpleNamespace(bot_config=SimpleNamespace(find_one=AsyncMock(return_value=None)))
    run(content.choose_document(ctx=context(), action_id="root", mongo=db, bot=SimpleNamespace()))
    opened = content.new_draft.await_args.args[1]
    assert opened["saved_snapshot"] == content.draft_snapshot(opened)
    assert not content.has_unsaved_edits(opened)

    monkeypatch.setattr(content, "load", AsyncMock(return_value=(dict(opened, _id="opened"), None)))
    result = run(content.back_to_root(ctx=context(), action_id="opened", mongo=db))
    assert "Recruit Gauntlet" in str(result[0].build())
    assert "Leave without saving" not in str(result[0].build())
    assert content.new_draft.await_count == 2


def test_home_warns_only_for_real_text_or_media_edits_and_reverts(monkeypatch):
    from extensions.commands.recruit import perms
    monkeypatch.setattr(perms, "is_recruiter", AsyncMock(return_value=False))
    document = content.DOCUMENTS["about-us"]
    sections = [node.content for node in content.text_nodes(run(content.baseline(document)))]
    state = {
        "_id": "draft", "user_id": 1, "guild_id": 2, "view": "document",
        "document": "about-us", "sections": sections, "media": {},
        "manage_token": "home-token", "revision": 0,
    }
    state["saved_snapshot"] = content.draft_snapshot(state)
    state["destination_channel_id"] = 123  # Saved separately; never a template edit.
    assert not content.has_unsaved_edits(state)
    monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
    home_state = {"_id": "home-token", "view": "home", "user_id": 1, "guild_id": 2}
    monkeypatch.setattr(manage, "get_state", AsyncMock(return_value=home_state))
    clean = run(content.manage_review(ctx=context(), action_id="draft", mongo=object()))
    assert "Server Management" in str(clean[0].build())
    assert manage.get_state.await_count == 1
    manage.get_state.return_value = dict(home_state, user_id=99)
    denied_home = run(content.manage_review(ctx=context(), action_id="draft", mongo=object()))
    assert "Open your own" in str(denied_home[0].build())

    changed = copy.deepcopy(state)
    changed["sections"][0] += " changed"
    monkeypatch.setattr(content, "load", AsyncMock(return_value=(changed, None)))
    warning = run(content.manage_review(ctx=context(), action_id="draft", mongo=object()))
    assert "Unsaved edits" in str(warning[0].build())
    back_warning = run(content.back_to_root(ctx=context(), action_id="draft", mongo=object()))
    assert "Leave without saving" in str(back_warning[0].build())
    assert manage.get_state.await_count == 2
    changed["sections"][0] = sections[0]
    assert not content.has_unsaved_edits(changed)
    changed["media"] = {"welcome": "https://cdn.discordapp.com/attachments/1/2/image.png?ex=old"}
    changed["saved_snapshot"] = content.draft_snapshot(changed)
    changed["media"]["welcome"] = "https://cdn.discordapp.com/attachments/1/2/image.png?ex=new"
    assert not content.has_unsaved_edits(changed)
    changed["media"]["welcome"] = "https://example.org/other.png"
    assert content.has_unsaved_edits(changed)
    changed["media"]["welcome"] = "https://cdn.discordapp.com/attachments/1/2/image.png?ex=old"
    assert not content.has_unsaved_edits(changed)


def test_successful_save_refreshes_snapshot_and_old_draft_warns(monkeypatch):
    document = content.DOCUMENTS["about-us"]
    sections = [node.content for node in content.text_nodes(run(content.baseline(document)))]
    state = {
        "_id": "draft", "user_id": 1, "guild_id": 2, "view": "document",
        "document": "about-us", "sections": sections, "media": {},
        "revision": 0, "manage_token": "home-token",
    }
    assert content.has_unsaved_edits(state)  # Old 30-minute panels lack a snapshot.
    state["saved_snapshot"] = content.draft_snapshot(state)
    state["sections"] = list(state["sections"])
    state["sections"][0] = "edited"
    monkeypatch.setattr(content, "load", AsyncMock(return_value=(state, None)))
    monkeypatch.setattr(content, "_save", AsyncMock(return_value=False))
    monkeypatch.setattr(content, "new_draft", AsyncMock(side_effect=lambda _db, row: dict(row, _id="saved")))
    run(content.save(ctx=context(), action_id="draft", mongo=object()))
    content.new_draft.assert_not_awaited()
    assert content.has_unsaved_edits(state)
    content._save.return_value = True
    run(content.save(ctx=context(), action_id="draft", mongo=object()))
    saved = content.new_draft.await_args.args[1]
    assert saved["revision"] == 1
    assert saved["saved_snapshot"] == content.draft_snapshot(saved)
    assert saved["saved_snapshot"]["sections"][0] == "edited"
    assert not content.has_unsaved_edits(saved)
