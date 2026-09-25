"""Schema module for the FWA sync panel storage (docs/mongodb-refactor.md rule 5).

Owns SCHEMA_VERSION, the constructor and `normalize_*` for each of the four
`fwa_sync_*` collections declared in `utils/mongo.py`, plus the pure recipient
helper shared by the poller and (in a later brief) the panel/DM UI. Nothing
here touches Mongo or Discord - see extensions/tasks/band_sync_ical.py for the
async shell that reads and writes through these shapes.

Collections, each covered by TTL(expire_at) 7 days after the event starts
(see docs/mongodb-refactor.md rule 11):
  fwa_sync_config     - singleton, _id="config", permanent (no TTL)
  fwa_sync_events     - _id="event:{uid}"
  fwa_sync_responses  - _id="{uid}|{user_id}"
  fwa_sync_deliveries - _id="delivery:{uid}|{event_version}|{offset}|{user_id}"
"""

from datetime import timedelta

# Only used for its NOTIFICATION_CHANNEL_ID constant, so a brand-new fwa_sync_config
# doc defaults its panel to the channel the old post-monitor panel used to post in
# (band-sync-panel-restyle) - band_monitor has no import back to this module, so this
# does not cycle. Pulling in the rest of band_monitor's Discord/aiohttp surface for one
# int is a real cost, but a second copy of the id would drift from it silently.
from extensions.tasks.band_monitor import NOTIFICATION_CHANNEL_ID

SCHEMA_VERSION = 1

CONFIG_ID = "config"
DEFAULT_OFFSETS = [60, 10, 0]
EVENT_TTL_DAYS = 7

RESPONSE_STATUSES = (None, "in", "maybe", "no")
DELIVERY_TYPES = ("reminder", "once")

# DECISIONS.md D007: reminders go to Yes and Maybe alike, not only Yes - the single set
# both recipients_for_offset below and the panel handler/status-change clearing in
# band_sync_panel.py import, so the rule lives in one place.
REMINDER_STATUSES = {"in", "maybe"}


# ---- Ids ----
def event_id(uid) -> str:
    return f"event:{uid}"


def event_version(event) -> str:
    """Unix-second string of the (already normalized) start time.

    `event["start"]` is expected to already be an aware UTC datetime - callers pass the
    feed event dict, never a raw Mongo document, so no normalize_start() call happens
    here (that would create an import cycle with band_ical_parser for no benefit).
    """
    return str(int(event["start"].timestamp()))


def delivery_id(event, offset, user_id) -> str:
    return f"delivery:{event['uid']}|{event_version(event)}|{offset}|{user_id}"


def response_id(uid, user_id) -> str:
    return f"{uid}|{user_id}"


# ---- Constructors ----
def new_config_doc(**overrides) -> dict:
    """The fwa_sync_config singleton, defaults filled, overrides applied last."""
    doc = {
        "_id": CONFIG_ID,
        "enabled": False,
        # Defaults to the post-monitor's old notification channel so a brand-new
        # install posts the one restyled panel somewhere sane without an admin having
        # to run Sync & Reminders channel selection first (band-sync-panel-restyle).
        "panel_channel_id": NOTIFICATION_CHANNEL_ID,
        # {uid, channel_id, message_id} of the panel currently posted, or None. Lives on
        # the config singleton (not the event row) so it survives purge_finished_events()
        # deleting the old event's row - see DECISIONS.md D013.
        "current_panel": None,
        # Open BAND link button target, settable via Sync & Reminders. Falls back
        # to this BAND page whenever an event carries no url of its own (the iCal
        # parser does not extract one today - see docs/band-sync-panel.md).
        "band_url": "https://www.band.us/band/94643112",
        "offsets": list(DEFAULT_OFFSETS),
        "announce_on_discovery": True,
        # Kept for load_config()/poll_once() - not part of the panel design, but
        # already-live operational knobs this schema must not drop.
        "summary_filter": "sync",
        "poll_seconds": 300,
        "stale_hours": 26,
        "schema_version": SCHEMA_VERSION,
    }
    doc.update(overrides)
    doc.pop("legacy_broadcast", None)
    doc.pop("dm_user_ids", None)
    return doc


def normalize_config(doc) -> dict:
    """Fill any missing field with its default; never trust a raw Mongo read."""
    defaults = new_config_doc()
    if not doc:
        return defaults
    merged = dict(defaults)
    for key in defaults:
        if key in doc:
            merged[key] = doc[key]
    merged["_id"] = CONFIG_ID
    merged["schema_version"] = SCHEMA_VERSION
    merged["offsets"] = list(merged.get("offsets") or DEFAULT_OFFSETS)
    # new_config_doc()'s NOTIFICATION_CHANNEL_ID default only ever lands on a
    # brand-new doc; an existing doc stored with panel_channel_id: None (or the key
    # missing) would otherwise stay None forever and never post a panel
    # (refuter-01 must-fix 3). `is None` specifically (not falsy) so an admin/test
    # that deliberately stores 0 to opt a doc out of panel posting still can -
    # post_or_replace_panel's `if not channel_id` already treats 0 the same as None.
    if merged.get("panel_channel_id") is None:
        merged["panel_channel_id"] = defaults["panel_channel_id"]
    return merged


def new_event_doc(event, closed_offsets=None, panel_channel_id=None,
                   panel_message_id=None, first_seen=None, now=None) -> dict:
    """One durable row per BAND sync event, replacing the old mixed event_state kind."""
    now = now or event["start"]
    return {
        "_id": event_id(event["uid"]),
        "uid": event["uid"],
        "calendar": event.get("calendar"),
        "summary": event.get("summary"),
        "start_at": event["start"],
        "event_version": event_version(event),
        "panel_channel_id": panel_channel_id,
        "panel_message_id": panel_message_id,
        # The event_version last rendered into the panel message, or None until the
        # first successful post/edit. process_event compares this to event_version on
        # every poll and refreshes whenever they differ, so a refresh that failed or
        # was interrupted (bot restart) simply retries on the next poll instead of
        # depending on detect_reschedule firing again (refuter-06 must-fix).
        "panel_version": None,
        "closed_offsets": list(closed_offsets or ()),
        "scheduled_offsets": [],
        "first_seen": first_seen or now,
        "updated_at": now,
        "expire_at": event["start"] + timedelta(days=EVENT_TTL_DAYS),
    }


def normalize_event(doc) -> dict:
    doc = dict(doc or {})
    doc.setdefault("closed_offsets", [])
    doc.setdefault("scheduled_offsets", [])
    doc.setdefault("panel_channel_id", None)
    doc.setdefault("panel_message_id", None)
    doc.setdefault("panel_version", None)
    return doc


def new_response_doc(uid, user_id, start_at, event_version, status,
                      reminders=None, dm_channel_id=None, dm_message_id=None,
                      dm_delete_at=None, now=None) -> dict:
    """One row per user per event. Replaced in place on every status change, never
    appended - see docs/mongodb-refactor.md rule 10 for the CAS pattern the UI brief
    must use when writing this doc from a button click.

    dm_delete_at (DECISIONS.md D006) is the UTC instant the current dm_message_id
    auto-deletes at - set alongside dm_channel_id/dm_message_id whenever a DM is sent,
    unset (along with them) once it is deleted.
    """
    now = now or start_at
    return {
        "_id": response_id(uid, user_id),
        "uid": uid,
        "event_version": event_version,
        "user_id": user_id,
        "status": status,
        "reminders": list(reminders or ()),
        "dm_channel_id": dm_channel_id,
        "dm_message_id": dm_message_id,
        "dm_delete_at": dm_delete_at,
        "updated_at": now,
        "expire_at": start_at + timedelta(days=EVENT_TTL_DAYS),
    }


def normalize_response(doc) -> dict:
    doc = dict(doc or {})
    doc.setdefault("reminders", [])
    doc.setdefault("status", None)  # "hasn't responded" - distinct from "no" (chose Deny)
    doc.setdefault("dm_channel_id", None)
    doc.setdefault("dm_message_id", None)
    doc.setdefault("dm_delete_at", None)  # D006: set only while a sent DM is still live
    return doc


def new_delivery_doc(event, offset, user_id, delivery_type="reminder",
                      old_start=None, now=None) -> dict:
    now = now or event["start"]
    return {
        "_id": delivery_id(event, offset, user_id),
        "uid": event["uid"],
        "event_version": event_version(event),
        "offset": offset,
        "recipient_id": user_id,
        "delivery_type": delivery_type,
        "calendar": event.get("calendar"),
        "summary": event.get("summary"),
        "start_at": event["start"],
        "end_at": event.get("end"),
        "old_start_at": old_start,
        "status": "queued",
        "failure_count": 0,
        "queued_at": now,
        "status_updated_at": now,
        "expire_at": event["start"] + timedelta(days=EVENT_TTL_DAYS),
    }


def normalize_delivery(doc) -> dict:
    doc = dict(doc or {})
    doc.setdefault("failure_count", 0)
    doc.setdefault("delivery_type", "reminder")
    return doc


# ---- Pure helpers ----
def recipients_for_offset(config, responses, offset) -> list:
    """Who gets the reminder DM for this offset, in a stable order.

    `responses` is an iterable of (already status-filtered or not) response docs; only
    ones with status in REMINDER_STATUSES ("in" or "maybe", D007) and this offset in
    their own `reminders` count. Saved fixed-recipient lists are ignored.
    """
    ids = []
    seen = set()
    for response in responses or ():
        if response.get("status") not in REMINDER_STATUSES:
            continue
        if offset not in (response.get("reminders") or ()):
            continue
        user_id = response.get("user_id")
        try:
            user_id = int(user_id)
        except (TypeError, ValueError):
            continue
        if user_id <= 0 or user_id in seen:
            continue
        seen.add(user_id)
        ids.append(user_id)

    return ids
