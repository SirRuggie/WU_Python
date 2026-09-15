from datetime import datetime, timedelta, timezone

from extensions.tasks import band_sync_schema as schema


def _event(uid="sync-1", start=None):
    start = start or datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    return {
        "uid": uid,
        "start": start,
        "end": start + timedelta(minutes=40),
        "summary": "FWA high sync",
        "calendar": "Sync3",
    }


# ---- Ids ----
def test_event_id_and_version_and_delivery_id():
    event = _event()
    assert schema.event_id(event["uid"]) == "event:sync-1"
    assert schema.event_version(event) == str(int(event["start"].timestamp()))
    assert schema.delivery_id(event, "60", 42) == (
        f"delivery:sync-1|{schema.event_version(event)}|60|42"
    )


def test_response_id_is_uid_pipe_user_id():
    assert schema.response_id("sync-1", 42) == "sync-1|42"


# ---- Config ----
def test_new_config_doc_defaults():
    doc = schema.new_config_doc()
    assert doc["_id"] == "config"
    assert doc["enabled"] is False
    # band-sync-panel-restyle: defaults to the post-monitor's old notification channel
    # so a brand-new install has a working panel channel with no /fwasync set-channel.
    from extensions.tasks import band_monitor
    assert doc["panel_channel_id"] == band_monitor.NOTIFICATION_CHANNEL_ID
    assert doc["current_panel"] is None
    assert doc["offsets"] == [60, 10, 0]
    assert doc["legacy_broadcast"] is False
    assert doc["dm_user_ids"] == []
    assert doc["schema_version"] == schema.SCHEMA_VERSION


def test_normalize_config_carries_current_panel_through():
    partial = {"_id": "config", "current_panel": {"uid": "sync-1", "channel_id": 1, "message_id": 2}}
    normalized = schema.normalize_config(partial)
    assert normalized["current_panel"] == {"uid": "sync-1", "channel_id": 1, "message_id": 2}


def test_new_config_doc_overrides_apply_last():
    doc = schema.new_config_doc(enabled=True, dm_user_ids=[1, 2], legacy_broadcast=True)
    assert doc["enabled"] is True
    assert doc["dm_user_ids"] == [1, 2]
    assert doc["legacy_broadcast"] is True


def test_normalize_config_fills_missing_fields_and_pins_schema_version():
    partial = {"_id": "config", "enabled": True, "schema_version": 999}
    normalized = schema.normalize_config(partial)
    assert normalized["enabled"] is True
    assert normalized["offsets"] == [60, 10, 0]  # missing -> default
    assert normalized["legacy_broadcast"] is False
    assert normalized["schema_version"] == schema.SCHEMA_VERSION  # never trust a raw read


def test_normalize_config_of_empty_doc_returns_defaults():
    assert schema.normalize_config(None) == schema.new_config_doc()
    assert schema.normalize_config({}) == schema.new_config_doc()


# ---- an existing doc stored with panel_channel_id: None (or the key absent) must
# still fall back to NOTIFICATION_CHANNEL_ID - the default in new_config_doc() only
# ever applies to brand-new docs (refuter-01 must-fix 3) ----
def test_normalize_config_falls_back_to_notification_channel_when_panel_channel_id_is_none():
    from extensions.tasks import band_monitor
    stored = {"_id": "config", "panel_channel_id": None}
    normalized = schema.normalize_config(stored)
    assert normalized["panel_channel_id"] == band_monitor.NOTIFICATION_CHANNEL_ID


def test_normalize_config_falls_back_to_notification_channel_when_key_absent():
    from extensions.tasks import band_monitor
    stored = {"_id": "config", "enabled": True}
    normalized = schema.normalize_config(stored)
    assert normalized["panel_channel_id"] == band_monitor.NOTIFICATION_CHANNEL_ID


# ---- Event ----
def test_new_event_doc_shape_and_ttl():
    event = _event()
    doc = schema.new_event_doc(event, closed_offsets=["new"])
    assert doc["_id"] == "event:sync-1"
    assert doc["uid"] == "sync-1"
    assert doc["summary"] == "FWA high sync"
    assert doc["event_version"] == schema.event_version(event)
    assert doc["panel_channel_id"] is None
    assert doc["panel_message_id"] is None
    assert doc["closed_offsets"] == ["new"]
    assert doc["scheduled_offsets"] == []
    assert doc["expire_at"] == event["start"] + timedelta(days=schema.EVENT_TTL_DAYS)


def test_normalize_event_fills_missing_fields():
    normalized = schema.normalize_event({"_id": "event:sync-1", "uid": "sync-1"})
    assert normalized["closed_offsets"] == []
    assert normalized["scheduled_offsets"] == []
    assert normalized["panel_channel_id"] is None
    assert normalized["panel_message_id"] is None


# ---- Response ----
def test_new_response_doc_shape_and_ttl():
    start = datetime(2026, 8, 5, 18, 0, tzinfo=timezone.utc)
    doc = schema.new_response_doc(
        "sync-1", 42, start, "v1", "in", reminders=[60, 10],
        dm_channel_id=1, dm_message_id=2,
    )
    assert doc["_id"] == "sync-1|42"
    assert doc["status"] == "in"
    assert doc["reminders"] == [60, 10]
    assert doc["dm_channel_id"] == 1
    assert doc["dm_message_id"] == 2
    assert doc["expire_at"] == start + timedelta(days=schema.EVENT_TTL_DAYS)


def test_normalize_response_fills_missing_fields():
    # refuter-04 noted, non-blocking: a missing status must default to None ("has not
    # responded", panel.STATUS_LINE's own key), not "no" ("chose Deny") - those are two
    # different signals for the panel/dm rendering to distinguish.
    normalized = schema.normalize_response({"_id": "sync-1|42", "user_id": 42})
    assert normalized["reminders"] == []
    assert normalized["status"] is None
    assert normalized["dm_channel_id"] is None
    assert normalized["dm_message_id"] is None


# ---- Delivery ----
def test_new_delivery_doc_shape_and_default_type_is_reminder():
    event = _event()
    doc = schema.new_delivery_doc(event, "60", 42)
    assert doc["delivery_type"] == "reminder"
    assert doc["status"] == "queued"
    assert doc["failure_count"] == 0
    assert doc["recipient_id"] == 42
    assert doc["offset"] == "60"
    assert doc["expire_at"] == event["start"] + timedelta(days=schema.EVENT_TTL_DAYS)


def test_new_delivery_doc_accepts_change_and_once_types():
    event = _event()
    assert schema.new_delivery_doc(event, "change:1", 1, "change")["delivery_type"] == "change"
    assert schema.new_delivery_doc(event, "new", 1, "once")["delivery_type"] == "once"


def test_normalize_delivery_fills_missing_fields():
    normalized = schema.normalize_delivery({"_id": "delivery:x"})
    assert normalized["failure_count"] == 0
    assert normalized["delivery_type"] == "reminder"
