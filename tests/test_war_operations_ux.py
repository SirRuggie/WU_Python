"""User-agreed publishing, autosave and return-ping lifecycle contracts."""
import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from extensions.commands import cwl_dashboard as ui, lazycwl_dashboard as returns
from extensions.commands.fwa import lazy_cwl_service as service
from extensions.tasks import cwl_reminder
from utils import cwl_campaign, lazy_cwl_store as store
from tests.test_cwl_dashboard_integration import MemoryMongo, StrictCampaignRest, install_runtime, modal_context
from tests.test_cwl_navigation import nodes
from tests.test_lazy_cwl_store import _Mongo, _list_doc, NOW


def test_publication_sends_saved_both_without_review_and_retries_only_failure(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        rest = StrictCampaignRest(failing_channels=[865726525990633472])
        install_runtime(monkeypatch, mongo, rest=rest)
        campaign = deepcopy(draft["campaign"])
        campaign["messages"]["roster"]["variants"]["main"]["body"] = "Fresh saved announcement"
        saved = await ui._save_campaign(mongo, draft, campaign)
        live = await cwl_campaign.load_campaign(mongo, 22, "2030-10")
        assert live["campaign"]["paused"] is True  # editing never starts reminders
        panel = await ui.publish_send(modal_context(), saved["token"] + "|both", mongo=mongo)
        rendered = str([c.build()[0] for c in panel])
        assert "Retry failed announcement" in rendered and "View post" in rendered
        assert len(rest.sent) == 1
        assert "Fresh saved announcement" in str([c.build()[0] for c in rest.sent[0]["components"]])
        rest.failing_channels.clear()
        await ui.publish_retry(modal_context(), saved["token"] + "|both", mongo=mongo)
        assert [r["channel"] for r in rest.sent] == [1072714594625257502, 865726525990633472]
        await ui.publish_send(modal_context(), saved["token"] + "|both", mongo=mongo)
        assert len(rest.sent) == 2
    asyncio.run(scenario())


def test_publication_and_landing_component_budgets_and_unique_ids(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        draft["manage_token"] = "m" * 32
        install_runtime(monkeypatch, mongo)
        for screen in [await ui.panel(draft, mongo=mongo), await ui.panel(draft, "schedule", mongo=mongo), await ui.publication_panel(draft, mongo)]:
            flattened = nodes(screen)
            assert len(flattened) <= 40
            ids = [n["custom_id"] for n in flattened if n.get("custom_id")]
            assert len(set(ids)) == len(ids)
            assert max(map(len, ids)) <= 100
        both = [n for n in nodes(await ui.publication_panel(draft, mongo)) if n.get("label") == "Both"][0]
        assert int(both["style"]) == 1
    asyncio.run(scenario())


def test_content_submit_saves_current_and_future_month_without_separate_save(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        install_runtime(monkeypatch, mongo)
        ctx = modal_context(values={"title": "Updated roster", "body": "Persistent message"})
        await ui.submit_text(ctx, draft["token"] + "|roster|lazy", mongo=mongo)
        for cycle in ["2030-10", "2030-11", "2031-02"]:
            saved = await cwl_campaign.load_campaign(mongo, 22, cycle)
            assert saved["campaign"]["messages"]["roster"]["variants"]["lazy"]["body"] == "Persistent message"
            assert saved["campaign"]["paused"] is True
        assert "Saved for future posts" in str(ctx.interaction.edit_initial_response.await_args)
    asyncio.run(scenario())


def test_content_edit_does_not_apply_a_retained_timing_change(monkeypatch):
    async def scenario():
        mongo = MemoryMongo()
        draft = await cwl_campaign.new_draft(mongo, 22, 11, cycle="2030-10")
        install_runtime(monkeypatch, mongo)
        campaign = deepcopy(draft["campaign"])
        campaign["messages"]["signup"]["schedule"]["day"] = 25
        draft = await cwl_campaign.patch_draft(mongo, draft["token"], {"campaign": campaign})
        campaign["messages"]["roster"]["variants"]["main"]["body"] = "New roster copy"
        await ui._save_campaign(mongo, draft, campaign)
        live = await cwl_campaign.load_campaign(mongo, 22, "2030-10")
        assert live["campaign"]["messages"]["signup"]["schedule"]["day"] == 20
        assert live["campaign"]["messages"]["roster"]["variants"]["main"]["body"] == "New roster copy"
    asyncio.run(scenario())


def test_return_pause_resume_and_frequency_preserve_first_start():
    async def scenario():
        mongo = _Mongo([_list_doc("one", expires_at=NOW + timedelta(days=12))])
        first = await store.set_reminders(mongo, "ABC", enabled=True, every_minutes=60, now=NOW)
        await store.record_reminder_sent(mongo, "one", now=NOW + timedelta(hours=1))
        await store.set_reminders(mongo, "ABC", enabled=False, every_minutes=None, now=NOW + timedelta(days=1))
        resumed = await store.set_reminders(mongo, "ABC", enabled=True, every_minutes=120, now=NOW + timedelta(days=2))
        assert resumed["reminders"]["started_at"] == first["reminders"]["started_at"] == NOW
        assert resumed["reminders"]["sent_count"] == 1
        with pytest.raises(ValueError, match="seven-day"):
            await store.set_reminders(mongo, "ABC", enabled=True, every_minutes=30, now=NOW + timedelta(days=7))
    asyncio.run(scenario())


def test_return_manual_send_refuses_expired_list(monkeypatch):
    doc = _list_doc("one", expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    monkeypatch.setattr(service.store, "get_active", AsyncMock(return_value=doc))
    lookup = AsyncMock()
    monkeypatch.setattr(service, "reminder_recipients", lookup)
    result = asyncio.run(service.remind_now("ABC"))
    assert not result["sent"] and "expired" in result["error"]
    lookup.assert_not_awaited()


def test_everyone_home_keeps_checking_then_pings_when_they_leave(monkeypatch):
    doc = _list_doc("one", expires_at=datetime.now(timezone.utc) + timedelta(days=5))
    doc["reminders"].update(enabled=True, every_minutes=60, started_at=datetime.now(timezone.utc))
    monkeypatch.setattr(service.store, "get_by_id", AsyncMock(return_value=doc))
    monkeypatch.setattr(service.store, "get_active", AsyncMock(return_value=doc))
    monkeypatch.setattr(service, "reminder_recipients", AsyncMock(side_effect=[[], [{"tag": "#P1"}]]))
    send = AsyncMock()
    stop = AsyncMock()
    monkeypatch.setattr(service, "_send_reminder_message", send)
    monkeypatch.setattr(service.store, "record_reminder_sent", AsyncMock())
    monkeypatch.setattr(service.store, "set_reminders", stop)
    asyncio.run(service.reminder_job("one"))
    send.assert_not_awaited()
    asyncio.run(service.reminder_job("one"))
    assert send.await_count == 1
    stop.assert_not_awaited()


def test_return_ui_opens_on_all_fwa_without_player_browser(monkeypatch):
    async def scenario():
        token = returns._session(11, 22)
        doc = _list_doc("one", clan_tag="ABC", expires_at=datetime.now(timezone.utc) + timedelta(days=5))
        monkeypatch.setattr(returns, "_clans", AsyncMock(return_value=[{"tag": "#ABC", "name": "Alpha"}]))
        monkeypatch.setattr(returns, "_active", AsyncMock(return_value=[doc]))
        monkeypatch.setattr(service, "away_players", AsyncMock(return_value=[]))
        rendered = await returns.build_home(object(), token=token)
        content = str([c.build()[0] for c in rendered])
        assert "Applies to all FWA clans" in content
        assert "Start Return Pings" in content and "Send Ping Now" in content
        assert "Search" not in content
    asyncio.run(scenario())


def test_bulk_retry_only_retries_failed_clans(monkeypatch):
    async def scenario():
        from tests.test_lazycwl_dashboard import _doc, _bound_session
        docs = [_doc(1), _doc(2)]
        token, nonce, ctx = _bound_session("send", docs)
        monkeypatch.setattr(returns, "_active", AsyncMock(return_value=docs))
        monkeypatch.setattr(returns, "build_home", AsyncMock(return_value=[]))
        send = AsyncMock(side_effect=[{"ok": True, "sent": True, "away_count": 1}, {"ok": False, "error": "Temporary failure"}, {"ok": True, "sent": True, "away_count": 2}])
        monkeypatch.setattr(service, "remind_now", send)
        await returns._apply_bound(object(), token, nonce, "send", ctx)
        retry = next(key for key, value in returns._sessions[token]["pending"].items() if value.get("retry"))
        await returns._apply_bound(object(), token, retry, "send", ctx)
        assert [call.args[0] for call in send.await_args_list] == ["#A1", "#A2", "#A2"]
        await returns._apply_bound(object(), token, retry, "send", ctx)
        assert send.await_count == 3
    asyncio.run(scenario())


@pytest.mark.parametrize("blocker", ["expired", "paused", "seven_days"])
def test_scheduled_send_rechecks_cutoff_and_pause_after_player_lookup(monkeypatch, blocker):
    now = datetime.now(timezone.utc)
    doc = _list_doc("one", expires_at=now + timedelta(days=2))
    doc["reminders"].update(enabled=True, started_at=now - timedelta(hours=1))
    current = deepcopy(doc)
    if blocker == "expired":
        current["expires_at"] = now - timedelta(seconds=1)
    elif blocker == "paused":
        current["reminders"]["enabled"] = False
    else:
        current["reminders"]["started_at"] = now - timedelta(days=7)
    monkeypatch.setattr(service.store, "get_active", AsyncMock(return_value=doc))
    monkeypatch.setattr(service.store, "get_by_id", AsyncMock(return_value=current))
    monkeypatch.setattr(service, "reminder_recipients", AsyncMock(return_value=[{"tag": "#P1"}]))
    send = AsyncMock()
    monkeypatch.setattr(service, "_send_reminder_message", send)
    result = asyncio.run(service.remind_now("ABC", scheduled=True))
    assert not result["sent"]
    send.assert_not_awaited()
