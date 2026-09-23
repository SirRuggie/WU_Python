"""Private Components V2 editor for the complete CWL message campaign.

The scheduler owns delivery.  This module deliberately owns only the editor:
it changes a durable campaign draft, previews the scheduler's renderer with
mentions suppressed, and asks the campaign service to apply a reviewed draft.
"""

from __future__ import annotations

import copy
import inspect
import re
import uuid
from datetime import datetime, timedelta
from typing import Any

import hikari
import lightbulb

from extensions.components import register_action
from utils.component_state import get_state, insert_state, utcnow
from utils.media_store import MediaStore, MediaStoreError
from utils.mongo import MongoClient
from utils import cwl_campaign
from utils import cwl_media
from utils import cwl_forms
from utils import cwl_review
from utils import cwl_sequence


loader = lightbulb.Loader()
cwl = lightbulb.Group(
    "cwl", "Configure CWL announcements and reminders",
    default_member_permissions=hikari.Permissions.ADMINISTRATOR,
)

NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
ACCENT = 0xD4AF37
ERROR = 0xB94444
AUDIENCES = ("main", "lazy")
MESSAGE_CHOICES = (
    ("signup", "Signups open"),
    ("reminder:1", "Reminder 1"),
    ("reminder:2", "Reminder 2"),
    ("reminder:3", "Reminder 3"),
    ("reminder:4", "Reminder 4"),
    ("reminder:5", "Reminder 5"),
    ("roster", "Rosters released"),
)


def can_edit(ctx: Any) -> bool:
    member = getattr(ctx.interaction, "member", None)
    permissions = getattr(member, "permissions", hikari.Permissions.NONE)
    return ctx.interaction.guild_id is not None and bool(
        permissions & hikari.Permissions.ADMINISTRATOR
    )


async def require_editor(ctx: Any) -> bool:
    if can_edit(ctx):
        return True
    await ctx.respond("Only administrators can manage CWL posts.", ephemeral=True)
    return False


def _campaign(draft: dict) -> dict:
    """The service stores a complete editable copy, never a sparse patch."""
    value = draft.get("campaign", draft.get("content", {}))
    return copy.deepcopy(value) if isinstance(value, dict) else {}


def _cycle(draft: dict) -> str:
    return str(draft.get("cycle") or draft.get("campaign_cycle") or "this month")


def _message_label(key: str) -> str:
    return dict(MESSAGE_CHOICES).get(key, key.replace(":", " ").title())


def _message_items(campaign: dict) -> list[tuple[str, str]]:
    """Known campaign steps first, then independently duplicated reminders."""
    messages = campaign.get("messages", {}) if isinstance(campaign.get("messages"), dict) else {}
    known = [(key, messages.get(key, {}).get("label", label)) for key, label in MESSAGE_CHOICES if key in messages]
    extras = [(key, value.get("label", _message_label(key))) for key, value in messages.items() if key not in dict(MESSAGE_CHOICES) and isinstance(value, dict)]
    return known + sorted(extras, key=lambda item: item[1].lower())


def _template(campaign: dict, key: str, audience: str) -> dict:
    messages = campaign.setdefault("messages", {})
    item = messages.setdefault(key, {})
    if not isinstance(item, dict):
        item = messages[key] = {}
    # Current campaign documents keep their Main/Lazy copy beneath variants.
    # The direct form remains readable so a partial legacy reminder migration
    # can be opened and saved without dropping its existing template.
    variants = item.setdefault("variants", {}) if "variants" in item else item
    template = variants.setdefault(audience, {})
    if not isinstance(template, dict):
        template = item[audience] = {}
    return template


def _schedule(campaign: dict, key: str) -> dict:
    message = campaign.setdefault("messages", {}).setdefault(key, {})
    value = message.setdefault("schedule", {})
    if not isinstance(value, dict):
        value = message["schedule"] = {}
    return value


def _short(value: Any, limit: int = 120) -> str:
    text = str(value or "").replace("\n", " ").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def _deadline(campaign: dict) -> str:
    rule = campaign.get("signup_deadline") or {}
    if not isinstance(rule, dict):
        return "Not set"
    if rule.get("at"):
        return str(rule["at"])
    if rule.get("day"):
        return f"Day {rule['day']} at {int(rule.get('hour', 17)):02}:{int(rule.get('minute', 0)):02}"
    return f"{int(rule.get('month_end_offset_days', 2))} days before month end at {int(rule.get('hour', 17)):02}:{int(rule.get('minute', 0)):02}"


def _deadline_input(campaign: dict) -> str:
    rule = campaign.get("signup_deadline") or {}
    if isinstance(rule, dict) and rule.get("at"):
        return str(rule["at"])
    if isinstance(rule, dict) and rule.get("day"):
        return f"{rule['day']} {int(rule.get('hour', 17)):02}:{int(rule.get('minute', 0)):02}"
    return f"end-{int(rule.get('month_end_offset_days', 2))} {int(rule.get('hour', 17)):02}:{int(rule.get('minute', 0)):02}"


def _time_description(schedule: dict) -> str:
    mode = str(schedule.get("mode") or "manual")
    if mode == "monthly":
        if "month_end_offset_days" in schedule:
            days = int(schedule["month_end_offset_days"])
            when = "last day of the month" if days == 0 else f"{days} day{'s' if days != 1 else ''} before month end"
            return f"Monthly · {when} at {int(schedule.get('hour', 0)):02}:{int(schedule.get('minute', 0)):02}"
        return f"Monthly · day {schedule.get('day', '?')} at {int(schedule.get('hour', 0)):02}:{int(schedule.get('minute', 0)):02}"
    if mode == "after_open":
        return f"{schedule.get('offset_minutes', 0)} minutes after signups open"
    if mode == "before_close":
        return f"{schedule.get('offset_minutes', 0)} minutes before signup close"
    if mode == "specific":
        return f"Specific · {schedule.get('at', schedule.get('datetime', 'not set'))}"
    if mode == "legacy_chain":
        return f"After previous · {schedule.get('offset_minutes', 0)} minutes"
    return "Manual"


def _is_sequence_reminder(key: str) -> bool:
    return bool(re.fullmatch(r"reminder:\d+", key))


def _next_cycle(cycle: str) -> str:
    """Return the first cycle affected by a monthly-defaults change."""
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(cycle))
    if not match:
        return str(cycle)
    year, month = int(match[1]), int(match[2])
    return f"{year + (month == 12):04d}-{1 if month == 12 else month + 1:02d}"


def _scope_cycle(draft: dict, scope: str | None = None) -> str:
    """Defaults begin after the actual active server cycle, never an old draft."""
    selected = str(scope or draft.get("scope") or "cycle")
    if selected != "defaults":
        return _cycle(draft)
    timezone = str(_campaign(draft).get("timezone") or "America/New_York")
    return _next_cycle(cwl_campaign.cycle_key(timezone_name=timezone))


def _future(value: Any, *, now: datetime | None = None) -> bool:
    if not value:
        return False
    try:
        return datetime.fromisoformat(str(value)) > (now or utcnow())
    except (TypeError, ValueError):
        return False


def _sequence_problem(campaign: dict, cycle: str) -> str | None:
    """A draft can be temporarily incomplete while opening/closing dates change."""
    if not campaign.get("reminder_sequence", {}).get("enabled"):
        return None
    try:
        cwl_campaign.resolve_schedule(campaign, cycle)
    except (TypeError, ValueError) as exc:
        return str(exc)
    return None


def _signup_opening(campaign: dict, cycle: str) -> str | None:
    """Resolve the chosen opening even while a reminder sequence is incomplete."""
    baseline = copy.deepcopy(campaign)
    settings = baseline.get("reminder_sequence")
    if isinstance(settings, dict):
        baseline["reminder_sequence"] = {**settings, "enabled": False}
    try:
        for occurrence in cwl_campaign.resolve_schedule(baseline, cycle):
            if occurrence.get("message_id") == "signup" and occurrence.get("run_at"):
                return str(occurrence["run_at"])
    except (TypeError, ValueError):
        pass
    return None


def _discord_time(value: Any) -> str:
    if not value:
        return "Not scheduled"
    try:
        return f"<t:{int(datetime.fromisoformat(str(value)).timestamp())}:F>"
    except (TypeError, ValueError):
        return str(value)


def _sequence_occurrences(campaign: dict, cycle: str) -> list[dict]:
    """One occurrence per numbered reminder; Main/Lazy variants share its time."""
    seen: set[str] = set()
    result = []
    for occurrence in cwl_campaign.resolve_schedule(campaign, cycle):
        key = str(occurrence.get("message_id", ""))
        if _is_sequence_reminder(key) and key not in seen:
            seen.add(key)
            result.append(occurrence)
    return result


def _sequence_summary(campaign: dict, cycle: str) -> str:
    config = campaign.get("reminder_sequence")
    if not isinstance(config, dict) or not config.get("enabled"):
        return "Each reminder uses its own time."
    try:
        all_occurrences = cwl_campaign.resolve_schedule(campaign, cycle)
        occurrences = _sequence_occurrences(campaign, cycle)
        opening = next((item.get("run_at") for item in all_occurrences if item.get("message_id") == "signup"), None)
        deadline = cwl_campaign.signup_deadline(campaign, cycle).isoformat()
    except ValueError as exc:
        return f"⚠️ Check these reminder settings before saving: {exc}"
    final = occurrences[-1].get("run_at") if occurrences else None
    mode = "Evenly spread" if config.get("mode") == "evenly" else f"Every {config.get('interval_hours')} hours"
    return (
        f"**{mode}** · {len(occurrences)} reminders in total, including the final reminder\n"
        f"Signups open: {_discord_time(opening)}\n"
        f"Signup deadline: {_discord_time(deadline)}\n"
        f"Final reminder: {_discord_time(final)} · {config.get('final_hours', 3)} hours before close"
    )


def _draft_token(draft: dict) -> str:
    """Discord custom ids are capped at 100 characters; use backend UUID token."""
    return str(draft.get("token") or draft["_id"])


def _parse_ref(action_id: str, expected: int = 1) -> tuple[str, ...] | None:
    values = tuple(str(action_id).split("|"))
    return values if len(values) == expected else None


def _split_ref(action_id: str) -> tuple[str, str] | None:
    """Split an opaque occurrence identifier once; occurrences contain pipes."""
    draft_id, separator, occurrence_id = str(action_id).partition("|")
    return (draft_id, occurrence_id) if separator and draft_id and occurrence_id else None


async def _load(ctx: Any, mongo: MongoClient, draft_id: str) -> tuple[dict | None, str | None]:
    draft = await cwl_campaign.load_draft(mongo, draft_id)
    if not draft:
        return None, "This draft is no longer available. Run `/cwl dashboard` to resume or create one."
    if not can_edit(ctx):
        return None, "Only administrators can manage CWL posts."
    if int(draft.get("user_id", draft.get("owner_id", 0))) != int(ctx.user.id):
        return None, "Open your own `/cwl dashboard`."
    if int(draft.get("guild_id", 0)) != int(ctx.interaction.guild_id):
        return None, "This CWL draft belongs to another server."
    return draft, None


async def _save_campaign(mongo: MongoClient, draft: dict, campaign: dict, **extra: Any) -> dict:
    # One whole campaign write prevents a text edit from accidentally losing an
    # image/button/schedule made in a previous modal.
    return await cwl_campaign.patch_draft(
        mongo, _draft_token(draft), {"campaign": campaign, **extra}
    )


async def _save_timing(ctx: Any, mongo: MongoClient, draft: dict, campaign: dict) -> tuple[dict, str]:
    """A submitted timing form updates the actual scheduler, not just an editor."""
    saved = await _save_campaign(mongo, draft, campaign)
    if saved.get("scope") != "cycle":
        saved = await cwl_campaign.patch_draft(mongo, _draft_token(saved), {"scope": "cycle"})
    try:
        result = await cwl_campaign.apply_draft(
            mongo, _draft_token(saved), int(ctx.user.id),
            expected_revision=saved.get("base_revision"), keep_draft=True, require_future_signup=True, repeat_monthly=True,
        )
    except (ValueError, RuntimeError) as exc:
        return saved, f"NOT SCHEDULED: {exc} Previous schedule kept. Fix the dates and try again."
    refreshed = result.get("draft") or saved
    if result.get("schedule_sync_pending"):
        return refreshed, "Settings saved, but the delivery queue could not be updated. Submit the timing form again to retry."
    if result.get("draft_refresh_pending"):
        return refreshed, "Schedule updated. Another edit was made at the same time; reopen the dashboard before saving again."
    if campaign.get("paused"):
        return refreshed, "Schedule saved. Automatic messages are paused; use Resume posts in Overview to turn them on."
    if saved.get("scope") == "defaults":
        return refreshed, "Saved for future months. This month's schedule has not changed."
    sent = set(result.get("sent_occurrences", ())) | {
        row.get("occurrence_id") for row in result.get("deliveries", ()) if row.get("status") == "sent"
    }
    remaining = [row for row in result["schedule"] if _future(row.get("run_at")) and row["id"] not in sent | set(result.get("skipped", ()))]
    if remaining:
        next_item = remaining[0]
        return refreshed, f"Scheduled. **{_message_label(next_item['message_id'])}** will send {_discord_time(next_item['run_at'])}."
    return refreshed, "Settings saved. No future messages are scheduled for this month."


async def _saved_defaults_campaign(mongo: MongoClient, guild_id: int) -> dict:
    """Match the defaults-draft baseline without importing a future override."""
    saved = await mongo.bot_config.find_one({"_id": cwl_campaign.defaults_id(guild_id)})
    if saved and isinstance(saved.get("campaign"), dict):
        return cwl_campaign._deep_merge(cwl_campaign.default_campaign(), saved["campaign"])
    if guild_id == cwl_campaign.LEGACY_WU_GUILD_ID:
        legacy_collection = getattr(mongo, "cwl_reminder", None)
        legacy = await legacy_collection.find_one({"_id": "schedule"}) if legacy_collection is not None else None
        return cwl_campaign.campaign_from_legacy(legacy)
    return cwl_campaign.default_campaign()


def _button(custom_id: str, label: str, *, style: hikari.ButtonStyle = hikari.ButtonStyle.SECONDARY) -> hikari.impl.MessageActionRowBuilder:
    row = hikari.impl.MessageActionRowBuilder()
    row.add_interactive_button(style, custom_id, label=label)
    return row


def _button_group(*items: tuple) -> hikari.impl.MessageActionRowBuilder:
    """Pack related controls into one Discord action row (maximum five)."""
    row = hikari.impl.MessageActionRowBuilder()
    for item in items:
        custom_id, label, style = item[:3]
        disabled = bool(item[3]) if len(item) == 4 else False
        row.add_interactive_button(style, custom_id, label=label, is_disabled=disabled)
    return row


def _tabs(draft_id: str, active: str) -> hikari.impl.MessageActionRowBuilder:
    row = hikari.impl.MessageActionRowBuilder()
    for tab, label in (("overview", "Overview"), ("messages", "Messages"), ("schedule", "Schedule")):
        row.add_interactive_button(
            hikari.ButtonStyle.PRIMARY if tab == active else hikari.ButtonStyle.SECONDARY,
            f"cwl_tab:{draft_id}|{tab}",
            label=label,
        )
    return row


def error_panel(message: str) -> list:
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=ERROR,
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"## CWL Dashboard\n{message}")],
    )]


def _header(draft: dict, tab: str, notice: str | None = None, *, navigation: bool = False) -> list:
    campaign = _campaign(draft)
    scope = str(draft.get("scope") or "cycle")
    target = _scope_cycle(draft, scope)
    month = datetime.strptime(target, "%Y-%m").strftime("%B %Y")
    target_label = f"For future months, starting **{month}**" if scope == "defaults" else f"For **{month}**"
    rows: list = [
        hikari.impl.TextDisplayComponentBuilder(content="## <:CWL:1399013745598009375> CWL announcements"),
        hikari.impl.TextDisplayComponentBuilder(
            content=f"{target_label} · **{campaign.get('timezone', 'America/New_York')}**\nRepeats monthly until changed."
        ),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    if navigation:
        rows.append(_tabs(_draft_token(draft), tab))
    return rows


async def panel(draft: dict, tab: str = "overview", notice: str | None = None, mongo: MongoClient | None = None) -> list:
    """Render a compact mobile-friendly editor panel from a durable draft."""
    # Old messages may still link to Settings. Keep those links working.
    if tab == "settings":
        tab = "schedule"
    if tab == "history":
        tab = "overview"
    campaign = _campaign(draft)
    draft_id = _draft_token(draft)
    display_cycle = _scope_cycle(draft)
    rows = _header(draft, tab, notice, navigation=True)

    if tab == "overview":
        live = await cwl_campaign.load_campaign(mongo, int(draft["guild_id"]), _cycle(draft)) if mongo is not None else None
        sent = {
            *{item.get("occurrence_id") for item in (live or {}).get("deliveries", ()) if item.get("status") == "sent"},
            *(live or {}).get("sent_occurrences", ()),
        }
        skipped = set((live or {}).get("skipped", ()))
        now = utcnow()
        draft_problem = _sequence_problem(campaign, display_cycle)
        live_pending = [
            entry for entry in (live or {}).get("schedule", ())
            if entry.get("id") not in sent | skipped and _future(entry.get("run_at"), now=now)
        ]
        live_next = live_pending[0] if live_pending else None
        live_text = "No more messages are scheduled for this month."
        live_campaign = (live or {}).get("campaign", {})
        paused = bool(live_campaign.get("paused", campaign.get("paused")))
        if live_next:
            live_text = f"**{_message_label(str(live_next.get('message_id', live_next.get('message_key', 'message'))))}** · {_discord_time(live_next.get('run_at', live_next.get('at')))}"
        if live is not None and paused:
            live_text = "Automatic messages are paused."
        saved_campaign = (await _saved_defaults_campaign(mongo, int(draft["guild_id"]))) if mongo is not None and draft.get("scope") == "defaults" else live_campaign
        changed = campaign != (saved_campaign if live is not None else draft.get("saved_campaign", campaign))
        status = "Unsaved changes. Save posts below, or submit a schedule to save all edits." if changed else "Saved."
        if live is None:
            status = "Save posts below. Schedule changes save all edits."
        if draft_problem:
            status = "Check the dates in Schedule before saving: " + draft_problem
        opening = _signup_opening(campaign, display_cycle)
        closing = cwl_campaign.signup_deadline(campaign, display_cycle).isoformat()
        sequence = campaign.get("reminder_sequence", {})
        if sequence.get("enabled"):
            timing = f"{sequence['count']} reminders, evenly spaced" if sequence.get("mode") == "evenly" else f"Every {sequence['interval_hours']} hours after signups open"
            reminder_text = f"{timing}. Final reminder {sequence['final_hours']} hours before signups close."
        else:
            reminder_text = "Custom reminder times."
        rows.extend([
            hikari.impl.SeparatorComponentBuilder(divider=True),
            hikari.impl.TextDisplayComponentBuilder(content=status),
            hikari.impl.TextDisplayComponentBuilder(content=f"### Signups open\n{_discord_time(opening)}\n### Signups close\n{_discord_time(closing)}\n### Reminders\n{reminder_text}"),
            _button_group(
                (f"cwl_save_options:{draft_id}|overview", "Save posts", hikari.ButtonStyle.SUCCESS, not changed),
            ),
        ])
        if live is not None:
            rows.append(_button(f"cwl_pause:{draft_id}", "Resume posts" if paused else "Pause posts", style=hikari.ButtonStyle.SUCCESS if paused else hikari.ButtonStyle.SECONDARY))
        if not changed:
            rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"### Next message\n{live_text}"))
            if live_next and live_next.get("id") and not paused:
                rows.append(_button(f"cwl_skip:{draft_id}|{live_next['id']}", "Skip this message", style=hikari.ButtonStyle.SECONDARY))

    elif tab == "messages":
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="### Messages\nChoose a Main Clan or Lazy CWL post."))
        menu_row = hikari.impl.MessageActionRowBuilder()
        menu = menu_row.add_text_menu(
            f"cwl_message:{draft_id}", min_values=1, placeholder="Choose a message version"
        )
        active_sequence = set()
        if campaign.get("reminder_sequence", {}).get("enabled"):
            try:
                active_sequence = {item["message_id"] for item in _sequence_occurrences(campaign, display_cycle)}
            except ValueError:
                # The Schedule panel explains how to repair an invalid sequence;
                # Messages must remain usable so the artwork/copy can be fixed.
                pass
        for key, label in _message_items(campaign)[:12]:
            for audience in AUDIENCES:
                template = _template(campaign, key, audience)
                if _is_sequence_reminder(key) and campaign.get("reminder_sequence", {}).get("enabled") and key not in active_sequence:
                    suffix = "not used this month"
                else:
                    suffix = "disabled" if template.get("enabled") is False else _short(template.get("title") or template.get("body") or "Untitled", 45)
                menu.add_option(f"{label} · {audience.title()}", f"{key}|{audience}", description=suffix)
        rows.append(menu_row)
        rows.append(_button(f"cwl_add_reminder:{draft_id}", "Configure reminders" if campaign.get("reminder_sequence", {}).get("enabled") else "Add reminder from signup", style=hikari.ButtonStyle.PRIMARY))
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="Preview has no pings. Save edits from Overview."))

    elif tab == "schedule":
        timezone = str(campaign.get("timezone") or "America/New_York")
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"### Schedule\nSubmitting saves all edits and schedules your CWL posts.\nEnter **{timezone}** times. Dates below show your local time."))
        unique: dict[str, dict] = {}
        timeline_error = None
        try:
            for item in cwl_campaign.resolve_schedule(campaign, display_cycle, now=utcnow()):
                if item.get("run_at"):
                    unique.setdefault(str(item["message_id"]), item)
        except (TypeError, ValueError) as exc:
            timeline_error = str(exc)
        # The opening is editable independently from automatic reminders. Keep
        # it visible even if a temporarily impossible sequence cannot resolve.
        opening = _signup_opening(campaign, display_cycle)
        try:
            closing = cwl_campaign.signup_deadline(campaign, display_cycle).isoformat()
        except (TypeError, ValueError):
            closing = None
        rows.extend([
            hikari.impl.TextDisplayComponentBuilder(content=f"### 1. Signups open\n{_discord_time(opening)}"),
            _button(f"cwl_edit_opening:{draft_id}", "Edit signups opening", style=hikari.ButtonStyle.PRIMARY),
            hikari.impl.TextDisplayComponentBuilder(content=f"### 2. Signups close\n{_discord_time(closing)}"),
            _button(f"cwl_edit_closing:{draft_id}", "Edit signup closing", style=hikari.ButtonStyle.PRIMARY),
            hikari.impl.TextDisplayComponentBuilder(content="### 3. Reminders"),
        ])
        sequence = campaign.get("reminder_sequence") or {}
        if sequence.get("enabled"):
            summary = (f"{sequence['count']} reminders, evenly spaced" if sequence.get("mode") == "evenly"
                       else f"Every {sequence['interval_hours']} hours")
            summary += f". Final reminder {sequence['final_hours']} hours before signups close."
        else:
            summary = "Set a reminder count or hourly gap."
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=summary))
        rows.append(_button(f"cwl_sequence_open:{draft_id}", "Edit reminders", style=hikari.ButtonStyle.PRIMARY))
        if timeline_error:
            rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"**NOT SCHEDULED:** {timeline_error} Correct the opening or closing date. The previous sending schedule stays unchanged."))
        occurrences = [item for item in unique.values() if _future(item.get("run_at"))][:5]
        if opening and not _future(opening):
            rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# The signup time {_discord_time(opening)} has passed. To schedule a new signup message, choose a future date and time."))
        if occurrences:
            lines = [f"• {_message_label(str(item.get('message_id', item.get('message_key', 'message'))))}: {_discord_time(item.get('run_at', item.get('at')))}" for item in occurrences]
            rows.append(hikari.impl.TextDisplayComponentBuilder(content="### Message times\n" + "\n".join(lines)))
        rows.append(_button_group(
            (f"cwl_advanced:{draft_id}", "More options", hikari.ButtonStyle.SECONDARY),
        ))

    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


def message_editor(draft: dict, key: str, audience: str, notice: str | None = None) -> list:
    campaign = _campaign(draft)
    template = _template(campaign, key, audience)
    try:
        default_artwork = cwl_campaign.default_campaign()["messages"][key]["variants"][audience]["media_url"]
    except KeyError:
        default_artwork = None
    can_restore_artwork = bool(default_artwork and template.get("media_url") != default_artwork)
    ref = f"{_draft_token(draft)}|{key}|{audience}"
    rows = _header(draft, "messages", notice)
    destination = hikari.impl.MessageActionRowBuilder()
    destination.add_channel_menu(
        f"cwl_channel:{ref}", channel_types=(hikari.ChannelType.GUILD_TEXT, hikari.ChannelType.GUILD_NEWS),
        placeholder="Choose a channel", min_values=1, max_values=1,
    )
    ping_roles = hikari.impl.MessageActionRowBuilder()
    ping_roles.add_select_menu(
        hikari.ComponentType.ROLE_SELECT_MENU, f"cwl_roles:{ref}",
        placeholder="Choose roles to ping", min_values=0, max_values=10,
    )
    rows.extend([
        hikari.impl.SeparatorComponentBuilder(divider=True),
        hikari.impl.TextDisplayComponentBuilder(content=f"### {_message_label(key)} · {audience.title()}\n**{_short(template.get('title') or 'Untitled', 160)}**\n{_short(template.get('body') or 'No body text yet.', 500)}"),
        hikari.impl.TextDisplayComponentBuilder(content=f"Buttons: {len(template.get('buttons') or [])} · Destination: {'set' if template.get('destination_channel_id') else 'not set'} · Pings: {len(template.get('role_ids') or [])}"),
        destination,
        ping_roles,
        _button_group(
            (f"cwl_text:{ref}", "Edit text", hikari.ButtonStyle.PRIMARY),
            (f"cwl_image:{ref}", "Upload replacement", hikari.ButtonStyle.PRIMARY),
            (f"cwl_links:{ref}", "Edit buttons", hikari.ButtonStyle.PRIMARY),
        ),
        _button_group(
            (f"cwl_copy_text:{ref}", "Copy text", hikari.ButtonStyle.SECONDARY),
            (f"cwl_duplicate_message:{ref}", "Duplicate", hikari.ButtonStyle.SECONDARY),
            (f"cwl_share_image:{ref}", "Share artwork", hikari.ButtonStyle.SECONDARY),
            (f"cwl_reset_image:{ref}", "Restore default image", hikari.ButtonStyle.SECONDARY, not can_restore_artwork),
        ),
        _button_group(
            (f"cwl_preview:{ref}", "Preview", hikari.ButtonStyle.SUCCESS),
            (f"cwl_toggle:{ref}", "Enable" if template.get("enabled") is False else "Disable", hikari.ButtonStyle.DANGER if template.get("enabled") is not False else hikari.ButtonStyle.SUCCESS),
            *((f"cwl_manual:{ref}", "Send roster", hikari.ButtonStyle.SUCCESS),) if key == "roster" else (),
            (f"cwl_tab:{_draft_token(draft)}|messages", "Back to Messages", hikari.ButtonStyle.SECONDARY),
        ),
    ])
    if template.get("media_url"):
        rows.insert(5, hikari.impl.MediaGalleryComponentBuilder(items=[
            hikari.impl.MediaGalleryItemBuilder(media=str(template["media_url"]))
        ]))
        rows.insert(5, hikari.impl.TextDisplayComponentBuilder(content="### Post image"))
        rows.insert(7, hikari.impl.TextDisplayComponentBuilder(
            content="-# Save posts from Overview to use this artwork."
        ))
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


async def _modal_source(ctx: Any, components: list) -> None:
    await _ack_modal(ctx)
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)


async def _ack_modal(ctx: Any) -> None:
    """Acknowledge a modal before any DB/R2 work, exactly once."""
    sent = getattr(ctx, "_initial_response_sent", None)
    if getattr(ctx, "_cwl_modal_acked", False) or (sent is not None and getattr(sent, "is_set", lambda: False)()):
        return
    interaction = ctx.interaction
    if getattr(interaction, "message", None) is not None:
        await interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)
    if sent is not None and hasattr(sent, "set"):
        sent.set()
    try:
        ctx._cwl_modal_acked = True
    except (AttributeError, TypeError):
        # Real Lightbulb contexts carry _initial_response_sent; tests and a few
        # lightweight contexts can use the event-less one-shot path above.
        pass


def _modal_value(ctx: Any, custom_id: str) -> str:
    for row in getattr(ctx.interaction, "components", ()):
        for component in row:
            if component.custom_id == custom_id:
                return str(component.value or "")
    return ""


@cwl.register()
class CWLDashboard(lightbulb.SlashCommand, name="dashboard", description="Edit CWL messages, schedules, and delivery settings"):
    cycle = lightbulb.string("cycle", "Optional cycle in YYYY-MM; defaults to the active CWL cycle", default=None)

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(self, ctx: Any, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        if not await require_editor(ctx):
            return
        await ctx.defer(ephemeral=True)
        selected_cycle = (await cwl_campaign.load_campaign(mongo, int(ctx.interaction.guild_id), self.cycle))["cycle"]
        draft = await cwl_campaign.find_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=selected_cycle)
        resumed = draft is not None
        if draft is None:
            draft = await cwl_campaign.new_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=selected_cycle)
        await ctx.respond(components=await panel(draft, "overview", "Resumed your saved CWL draft." if resumed else None, mongo=mongo), ephemeral=True, **NO_MENTIONS)


async def open_dashboard(ctx: Any, mongo: MongoClient, *, bot: Any = None, cycle: str | None = None) -> dict | None:
    """Open a CWL draft from another already-deferred private dashboard panel."""
    if not await require_editor(ctx):
        return None
    selected_cycle = (await cwl_campaign.load_campaign(mongo, int(ctx.interaction.guild_id), cycle))["cycle"]
    draft = await cwl_campaign.find_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=selected_cycle)
    resumed = draft is not None
    if draft is None:
        draft = await cwl_campaign.new_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=selected_cycle)
    await ctx.interaction.edit_initial_response(components=await panel(draft, "overview", "Resumed your saved CWL draft." if resumed else None, mongo=mongo), **NO_MENTIONS)
    return draft


@register_action("cwl_tab", preload_state=False)
@lightbulb.di.with_di
async def tab(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 2)
    if not ref:
        return error_panel("This dashboard panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    return error_panel(problem) if problem else await panel(draft, ref[1], mongo=mongo)


@register_action("cwl_message", preload_state=False)
@lightbulb.di.with_di
async def choose_message(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    values = getattr(ctx.interaction, "values", ())
    if len(values) != 1 or len(values[0].split("|")) != 2:
        return await panel(draft, "messages", "Choose one message version.")
    key, audience = values[0].split("|", 1)
    if key not in _campaign(draft).get("messages", {}) or audience not in AUDIENCES:
        return await panel(draft, "messages", "Choose one supported message version.")
    return message_editor(draft, key, audience)


@register_action("cwl_save_options", preload_state=False)
@lightbulb.di.with_di
async def save_options(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 2)
    if not ref or ref[1] not in {"overview", "schedule"}:
        return error_panel("Open the dashboard again to save your changes.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    live = await cwl_campaign.load_campaign(mongo, int(draft["guild_id"]), _cycle(draft))
    if _campaign(draft) == live["campaign"]:
        return await panel(draft, "overview", "No changes to save.", mongo=mongo)
    saved, notice = await _save_timing(ctx, mongo, draft, _campaign(draft))
    if notice.startswith("Scheduled."):
        notice = "Saved. Repeats monthly until changed."
    return await panel(saved, "overview", notice, mongo=mongo)


@register_action("cwl_sequence_open", preload_state=False)
@lightbulb.di.with_di
async def open_sequence(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    return error_panel(problem) if problem else sequence_panel(draft)


@register_action("cwl_advanced", preload_state=False)
@lightbulb.di.with_di
async def advanced(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    rows = _header(draft, "schedule")
    rows.append(hikari.impl.TextDisplayComponentBuilder(content="### More options\nChange one message's timing, or discard your edits and reload saved settings."))
    menu_row = hikari.impl.MessageActionRowBuilder()
    menu = menu_row.add_text_menu(f"cwl_schedule:{action_id}", min_values=1, placeholder="Choose a message")
    for key, label in _message_items(_campaign(draft))[:25]:
        menu.add_option(label, key)
    rows.extend([
        menu_row,
        _button(f"cwl_discard_review:{action_id}", "Discard changes…", style=hikari.ButtonStyle.DANGER),
        _button(f"cwl_tab:{action_id}|schedule", "Back to Schedule"),
    ])
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


@register_action("cwl_schedule", preload_state=False)
@lightbulb.di.with_di
async def choose_schedule(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    values = getattr(ctx.interaction, "values", ())
    if len(values) != 1 or values[0] not in _campaign(draft).get("messages", {}):
        return await panel(draft, "schedule", "Choose one message schedule.")
    key = values[0]
    if _is_sequence_reminder(key) and _campaign(draft).get("reminder_sequence", {}).get("enabled"):
        return sequence_panel(draft, "Numbered reminders are timed by the reminder sequence. Edit the sequence instead of an individual time.")
    return schedule_editor(draft, key)


@register_action("cwl_edit_opening", preload_state=False)
@lightbulb.di.with_di
async def edit_opening(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    if "signup" not in _campaign(draft).get("messages", {}):
        return error_panel("Add a signup message before choosing its time.")
    return monthly_editor(draft, "signup")


def closing_editor(draft: dict, notice: str | None = None) -> list:
    rows = _header(draft, "schedule", notice)
    rows.extend([
        hikari.impl.SeparatorComponentBuilder(divider=True),
        hikari.impl.TextDisplayComponentBuilder(content="### 2. Signups close\nChoose a simple monthly closing rule. You can also choose one specific date."),
        _button_group(
            (f"cwl_edit_closing_mode:{_draft_token(draft)}|month_end", "Before month end", hikari.ButtonStyle.PRIMARY),
            (f"cwl_edit_closing_mode:{_draft_token(draft)}|day", "Day of month", hikari.ButtonStyle.PRIMARY),
            (f"cwl_edit_closing_mode:{_draft_token(draft)}|specific", "Specific date", hikari.ButtonStyle.SECONDARY),
        ),
        _button(f"cwl_tab:{_draft_token(draft)}|schedule", "Back to Schedule"),
    ])
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


@register_action("cwl_edit_closing", preload_state=False)
@lightbulb.di.with_di
async def edit_closing(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    return closing_editor(draft)


@register_action("cwl_edit_closing_mode", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_closing_mode(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 2)
    if not ref or ref[1] not in {"month_end", "day", "specific"}:
        await _modal_source(ctx, error_panel("Choose a supported signup-closing rule.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    campaign = _campaign(draft)
    await ctx.respond_with_modal(
        title="CWL signup closing", custom_id=f"cwl_submit_settings:{ref[0]}|{ref[1]}",
        components=cwl_forms.deadline_form(campaign.get("signup_deadline", {}), str(campaign.get("timezone") or "America/New_York"), mode=ref[1]),
    )


def sequence_panel(draft: dict, notice: str | None = None) -> list:
    campaign = _campaign(draft)
    draft_id = _draft_token(draft)
    rows = _header(draft, "schedule", notice)
    rows.extend([
        hikari.impl.SeparatorComponentBuilder(divider=True),
        hikari.impl.TextDisplayComponentBuilder(content="### Reminders\n" + _sequence_summary(campaign, _scope_cycle(draft))),
        hikari.impl.TextDisplayComponentBuilder(content="Edit reminder text and artwork in Messages."),
        _button_group(
            (f"cwl_sequence_even:{draft_id}", "Evenly spread reminders", hikari.ButtonStyle.PRIMARY),
            (f"cwl_sequence_interval:{draft_id}", "Every X hours", hikari.ButtonStyle.PRIMARY),
            *((
                (f"cwl_sequence_times:{draft_id}", "View all send times", hikari.ButtonStyle.SECONDARY),
                (f"cwl_sequence_disable:{draft_id}", "Turn off automatic reminders", hikari.ButtonStyle.DANGER),
            ) if campaign.get("reminder_sequence", {}).get("enabled") else ()),
            (f"cwl_tab:{draft_id}|schedule", "Back to Schedule", hikari.ButtonStyle.SECONDARY),
        ),
    ])
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


def _sequence_modal_components(mode: str, config: dict | None = None) -> list:
    config = config or {}
    items = []
    if mode == "evenly":
        items.append(hikari.impl.ModalActionRowBuilder().add_text_input("count", "How many reminders? (includes final; 4)", value=str(config.get("count", 4)), required=True, max_length=2))
    else:
        items.append(hikari.impl.ModalActionRowBuilder().add_text_input("interval_hours", "Every how many hours?", value=str(config.get("interval_hours", 48)), required=True, max_length=4))
    items.extend([
        hikari.impl.ModalActionRowBuilder().add_text_input("final_hours", "Hours before signups close", value=str(config.get("final_hours", 3)), required=True, max_length=3),
        hikari.impl.ModalActionRowBuilder().add_text_input("min_gap_hours", "At least this many hours apart", value=str(config.get("min_gap_hours", 3)), required=True, max_length=3),
    ])
    return items


@register_action("cwl_sequence_even", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def sequence_even(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    config = _campaign(draft).get("reminder_sequence")
    await ctx.respond_with_modal(title="Evenly spread reminders", custom_id=f"cwl_sequence_submit:{action_id}|evenly", components=_sequence_modal_components("evenly", config if isinstance(config, dict) else None))


@register_action("cwl_sequence_interval", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def sequence_interval(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    config = _campaign(draft).get("reminder_sequence")
    await ctx.respond_with_modal(title="Reminder interval", custom_id=f"cwl_sequence_submit:{action_id}|interval", components=_sequence_modal_components("interval", config if isinstance(config, dict) else None))


@register_action("cwl_sequence_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_sequence(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _ack_modal(ctx)
    ref = _parse_ref(action_id, 2)
    if not ref or ref[1] not in {"evenly", "interval"}:
        await _modal_source(ctx, error_panel("This reminder sequence form is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    values = {item.custom_id: str(item.value or "") for row in ctx.interaction.components for item in row}
    try:
        existing = _campaign(draft).get("reminder_sequence", {})
        count = cwl_forms._integer(values.get("count", existing.get("count", 4)), "Reminder count", 1, 10)
        interval = cwl_forms._integer(values.get("interval_hours", existing.get("interval_hours", 48)), "Interval hours", 1, 744)
        final = cwl_forms._integer(values.get("final_hours", ""), "Final reminder hours", 1, 744)
        gap = cwl_forms._integer(values.get("min_gap_hours", ""), "Minimum gap hours", 1, 24)
        campaign = cwl_sequence.configure(
            _campaign(draft), mode=ref[1], count=count, interval_hours=interval,
            final_hours=final, min_gap_hours=gap,
        )
        # Configure validates the plan, and this resolves again before the
        # durable save so malformed custom templates never become a draft.
        _sequence_occurrences(campaign, _scope_cycle(draft))
        saved, notice = await _save_timing(ctx, mongo, draft, campaign)
    except (TypeError, ValueError) as exc:
        await _modal_source(ctx, sequence_panel(draft, str(exc))); return
    await _modal_source(ctx, sequence_panel(saved, notice))


@register_action("cwl_sequence_disable", preload_state=False)
@lightbulb.di.with_di
async def disable_sequence(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    campaign = _campaign(draft)
    settings = campaign.get("reminder_sequence")
    if not isinstance(settings, dict) or not settings.get("enabled"):
        return await panel(draft, "schedule", "Automatic reminders are already off.")
    campaign["reminder_sequence"] = {**settings, "enabled": False}
    # Do not resurrect stale transitional schedules when the numbered slots go
    # back to individual timing.
    for key in campaign.get("messages", {}):
        if _is_sequence_reminder(str(key)):
            (campaign.get("schedules") or {}).pop(key, None)
            campaign["messages"][key]["schedule"] = {"mode": "manual"}
    saved, notice = await _save_timing(ctx, mongo, draft, campaign)
    return await panel(saved, "schedule", notice, mongo=mongo)


@register_action("cwl_sequence_times", preload_state=False)
@lightbulb.di.with_di
async def sequence_times(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    try:
        occurrences = _sequence_occurrences(_campaign(draft), _scope_cycle(draft))
    except ValueError as exc:
        return sequence_panel(draft, str(exc))
    lines = [f"• **{_message_label(str(item['message_id']))}**: {_discord_time(item.get('run_at'))}" for item in occurrences]
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=_header(draft, "schedule") + [
        hikari.impl.TextDisplayComponentBuilder(content="### All reminder send times\n" + ("\n".join(lines) or "No active reminder send times.")),
        hikari.impl.TextDisplayComponentBuilder(content="-# These times will be used after you save. Messages already sent or skipped will not be sent again."),
        _button(f"cwl_tab:{_draft_token(draft)}|schedule", "Back to Schedule"),
    ])]


def schedule_editor(draft: dict, key: str, notice: str | None = None) -> list:
    campaign = _campaign(draft)
    schedule = _schedule(campaign, key)
    rows = _header(draft, "schedule", notice)
    rows.extend([
        hikari.impl.SeparatorComponentBuilder(divider=True),
        hikari.impl.TextDisplayComponentBuilder(content=f"### {_message_label(key)}\n**{_time_description(schedule)}**\nMode: `{schedule.get('mode', 'manual')}`"),
        hikari.impl.TextDisplayComponentBuilder(content="Choose how this message is timed. The form uses calendar dates and ordinary minutes, hours, or days."),
        _button(f"cwl_tab:{_draft_token(draft)}|schedule", "Back to Schedule"),
    ])
    modes_row = hikari.impl.MessageActionRowBuilder()
    modes = modes_row.add_text_menu(
        f"cwl_schedule_mode:{_draft_token(draft)}|{key}", min_values=1, placeholder="Choose delivery timing"
    )
    for value, label in (("monthly", "Monthly"), ("after_open", "After signups open"), ("before_close", "Before signup deadline"), ("specific", "One-time date"), ("legacy_chain", "After previous reminder"), ("manual", "Manual")):
        modes.add_option(label, value, is_default=value == schedule.get("mode", "manual"))
    rows.insert(-1, modes_row)
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


def monthly_editor(draft: dict, key: str) -> list:
    ref = f"{_draft_token(draft)}|{key}"
    rows = _header(draft, "schedule") + [
        hikari.impl.TextDisplayComponentBuilder(content=(
            f"### Monthly · {_message_label(key)}\nChoose one way to set the monthly date. Then enter the number and delivery time.\n"
            "**Day of the month:** a date from 1–31. Shorter months use their last day.\n"
            "**Days before month end:** 0–27 days before the month's last day. 0 means the last day itself."
        )),
        _button_group(
            (f"cwl_monthly_choice:{ref}|day", "Day of the month", hikari.ButtonStyle.PRIMARY),
            (f"cwl_monthly_choice:{ref}|end", "Days before month end", hikari.ButtonStyle.PRIMARY),
        ),
        _button(f"cwl_tab:{_draft_token(draft)}|schedule", "Back to Schedule"),
    ]
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


async def _open_message_modal(ctx: Any, action_id: str, mongo: MongoClient, kind: str) -> None:
    ref = _parse_ref(action_id, 3)
    if not ref:
        await _modal_source(ctx, error_panel("This editor panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    template = _template(_campaign(draft), ref[1], ref[2])
    if kind == "text":
        components = [
            hikari.impl.ModalActionRowBuilder().add_text_input("dashboard_name", "Dashboard name", value=str(_campaign(draft).get("messages", {}).get(ref[1], {}).get("label") or _message_label(ref[1])), required=True, max_length=80),
            hikari.impl.ModalActionRowBuilder().add_text_input("title", "Title", value=str(template.get("title") or ""), required=True, max_length=256),
            hikari.impl.ModalActionRowBuilder().add_text_input("body", "Message text", value=str(template.get("body") or ""), required=True, max_length=4000, style=hikari.TextInputStyle.PARAGRAPH),
        ]
        title = "Edit CWL message"
    elif kind == "image":
        components = [hikari.impl.ModalActionRowBuilder().add_text_input("media_url", "Image URL", value=str(template.get("media_url") or ""), required=False, max_length=1000)]
        title = "Change CWL artwork"
    elif kind == "links":
        lines = "\n".join(" | ".join(str(item.get(field, "")) for field in ("label", "url", "emoji")) for item in template.get("buttons", ()) if isinstance(item, dict))
        components = [hikari.impl.ModalActionRowBuilder().add_text_input("buttons", "Label | URL | emoji (one per line)", value=lines, required=False, max_length=4000, style=hikari.TextInputStyle.PARAGRAPH)]
        title = "Edit CWL buttons"
    else:
        components = [
            hikari.impl.ModalActionRowBuilder().add_text_input("channel", "Destination channel ID", value=str(template.get("destination_channel_id") or ""), required=False, max_length=30),
            hikari.impl.ModalActionRowBuilder().add_text_input("roles", "Role IDs to ping (comma separated)", value=", ".join(map(str, template.get("role_ids") or ())), required=False, max_length=500),
        ]
        title = "Edit channel and mentions"
    await ctx.respond_with_modal(title=title, custom_id=f"cwl_submit_{kind}:{action_id}", components=components)


@register_action("cwl_text", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_text(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _open_message_modal(ctx, action_id, mongo, "text")


@register_action("cwl_image", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_image(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        await _modal_source(ctx, error_panel("This editor panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    # The pinned SDK cannot decode Discord's new file-upload modal component.
    # Keep its complete immutable target in the signed-in interaction custom ID;
    # storing a shared "current upload target" in the draft would let two open
    # modals race and put otherwise valid artwork on the wrong message.
    await ctx.respond_with_modal(
        title=f"Upload {_message_label(ref[1])} artwork"[:45],
        custom_id=f"cwl_image_submit:{action_id}",
        components=cwl_media.upload_modal_components(),
    )


@register_action("cwl_links", preload_state=False)
@lightbulb.di.with_di
async def edit_links(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    return error_panel(problem) if problem else links_editor(draft, ref[1], ref[2])


def links_editor(draft: dict, key: str, audience: str, notice: str | None = None) -> list:
    template = _template(_campaign(draft), key, audience)
    ref = f"{_draft_token(draft)}|{key}|{audience}"
    rows = _header(draft, "messages", notice)
    rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"### Buttons · {_message_label(key)} · {audience.title()}\nChoose one to edit it, or add a new link button."))
    buttons = template.get("buttons", [])
    if buttons:
        menu_row = hikari.impl.MessageActionRowBuilder()
        menu = menu_row.add_text_menu(f"cwl_button_choose:{ref}", min_values=1, placeholder="Choose a button")
        for index, button in enumerate(buttons):
            menu.add_option(str(button.get("label") or f"Button {index + 1}")[:100], str(index), description=_short(button.get("url"), 90))
        rows.append(menu_row)
    rows.append(_button(f"cwl_button_add:{ref}", "Add button", style=hikari.ButtonStyle.PRIMARY))
    rows.append(_button(f"cwl_open_message:{ref}", "Back to message"))
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=rows)]


@register_action("cwl_button_choose", preload_state=False)
@lightbulb.di.with_di
async def choose_button(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    values = getattr(ctx.interaction, "values", ())
    if len(values) != 1 or not values[0].isdigit():
        return links_editor(draft, ref[1], ref[2], "Choose one button.")
    index = int(values[0]); buttons = _template(_campaign(draft), ref[1], ref[2]).get("buttons", [])
    if not 0 <= index < len(buttons):
        return links_editor(draft, ref[1], ref[2], "That button no longer exists.")
    button = buttons[index]; full = f"{action_id}|{index}"
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=_header(draft, "messages") + [
        hikari.impl.TextDisplayComponentBuilder(content=f"### {_short(button.get('label'), 100)}\n{_short(button.get('url'), 300)}"),
        _button(f"cwl_button_edit:{full}", "Edit button", style=hikari.ButtonStyle.PRIMARY),
        _button(f"cwl_button_remove:{full}", "Remove button", style=hikari.ButtonStyle.DANGER),
        _button(f"cwl_links:{action_id}", "Back to buttons"),
    ])]


async def _button_modal(ctx: Any, action_id: str, mongo: MongoClient, *, index: int | None) -> None:
    ref = _parse_ref(action_id, 3 if index is None else 4)
    if not ref:
        await _modal_source(ctx, error_panel("This editor panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    selected = {} if index is None else _template(_campaign(draft), ref[1], ref[2]).get("buttons", [])[index]
    suffix = "new" if index is None else str(index)
    await ctx.respond_with_modal(title="CWL link button", custom_id=f"cwl_button_submit:{action_id}|{suffix}", components=[
        hikari.impl.ModalActionRowBuilder().add_text_input("label", "Button label", value=str(selected.get("label") or ""), required=True, max_length=80),
        hikari.impl.ModalActionRowBuilder().add_text_input("url", "Link URL", value=str(selected.get("url") or ""), required=True, max_length=1000),
        hikari.impl.ModalActionRowBuilder().add_text_input("emoji", "Emoji (optional)", value=str(selected.get("emoji") or ""), required=False, max_length=100),
    ])


@register_action("cwl_button_add", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def add_button(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _button_modal(ctx, action_id, mongo, index=None)


@register_action("cwl_button_edit", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_button(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 4)
    await _button_modal(ctx, action_id, mongo, index=int(ref[3]) if ref and ref[3].isdigit() else -1)


@register_action("cwl_button_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_button(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _ack_modal(ctx)
    ref = _parse_ref(action_id, 4)
    if not ref:
        await _modal_source(ctx, error_panel("This editor panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    label, url, emoji = _modal_value(ctx, "label").strip(), _modal_value(ctx, "url").strip(), _modal_value(ctx, "emoji").strip()
    buttons = _template(_campaign(draft), ref[1], ref[2]).setdefault("buttons", [])
    if not label or not url.startswith("https://"):
        await _modal_source(ctx, links_editor(draft, ref[1], ref[2], "A button needs a label and an https URL.")); return
    value = {"label": label, "url": url, "emoji": emoji}
    if ref[3] == "new":
        if len(buttons) >= 5:
            await _modal_source(ctx, links_editor(draft, ref[1], ref[2], "Discord supports at most five buttons.")); return
        buttons.append(value)
    elif ref[3].isdigit() and 0 <= int(ref[3]) < len(buttons):
        buttons[int(ref[3])] = value
    else:
        await _modal_source(ctx, links_editor(draft, ref[1], ref[2], "That button no longer exists.")); return
    campaign = _campaign(draft); _template(campaign, ref[1], ref[2])["buttons"] = buttons
    saved = await _save_campaign(mongo, draft, campaign)
    await _modal_source(ctx, links_editor(saved, ref[1], ref[2], "Button saved."))


@register_action("cwl_button_remove", preload_state=False)
@lightbulb.di.with_di
async def remove_button(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 4)
    if not ref or not ref[3].isdigit():
        return error_panel("This button is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    campaign = _campaign(draft); buttons = _template(campaign, ref[1], ref[2]).get("buttons", [])
    index = int(ref[3])
    if not 0 <= index < len(buttons):
        return links_editor(draft, ref[1], ref[2], "That button no longer exists.")
    buttons.pop(index)
    saved = await _save_campaign(mongo, draft, campaign)
    return links_editor(saved, ref[1], ref[2], "Button removed.")


@register_action("cwl_delivery", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_delivery(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _open_message_modal(ctx, action_id, mongo, "delivery")


@register_action("cwl_channel", preload_state=False)
@lightbulb.di.with_di
async def choose_channel(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    values = getattr(ctx.interaction, "values", ())
    if len(values) != 1 or not str(values[0]).isdigit():
        return message_editor(draft, ref[1], ref[2], "Choose one text or announcement channel.")
    campaign = _campaign(draft)
    _template(campaign, ref[1], ref[2])["destination_channel_id"] = int(values[0])
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, ref[1], ref[2], "Delivery channel updated.")


@register_action("cwl_roles", preload_state=False)
@lightbulb.di.with_di
async def choose_roles(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    values = getattr(ctx.interaction, "values", ())
    if len(values) > 10 or any(not str(value).isdigit() for value in values):
        return message_editor(draft, ref[1], ref[2], "Choose up to ten server roles.")
    campaign = _campaign(draft)
    _template(campaign, ref[1], ref[2])["role_ids"] = [int(value) for value in values]
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, ref[1], ref[2], "Ping roles updated.")


async def _submit_message(ctx: Any, action_id: str, mongo: MongoClient, kind: str) -> None:
    await _ack_modal(ctx)
    ref = _parse_ref(action_id, 3)
    if not ref:
        await _modal_source(ctx, error_panel("This editor panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    campaign = _campaign(draft); template = _template(campaign, ref[1], ref[2])
    try:
        if kind == "text":
            name = _modal_value(ctx, "dashboard_name").strip() or str(campaign["messages"][ref[1]].get("label") or _message_label(ref[1]))
            title, body = _modal_value(ctx, "title").strip(), _modal_value(ctx, "body").strip()
            if not title or not body:
                raise ValueError("Title and message text are required.")
            campaign["messages"][ref[1]]["label"] = name
            template.update(title=title, body=body)
        elif kind == "image":
            url = _modal_value(ctx, "media_url").strip()
            if url and not url.startswith("https://"):
                raise ValueError("Artwork must use an https URL.")
            template["media_url"] = url
        elif kind == "links":
            buttons = []
            for line in _modal_value(ctx, "buttons").splitlines():
                if not line.strip():
                    continue
                fields = [part.strip() for part in line.split("|")]
                if len(fields) not in {2, 3} or not fields[0] or not fields[1].startswith("https://"):
                    raise ValueError("Each button must be `Label | https://url | emoji`.")
                buttons.append({"label": fields[0], "url": fields[1], "emoji": fields[2] if len(fields) == 3 else ""})
            if len(buttons) > 5:
                raise ValueError("A Discord message can have at most five buttons.")
            template["buttons"] = buttons
        else:
            channel, roles = _modal_value(ctx, "channel").strip(), _modal_value(ctx, "roles").strip()
            if channel and not channel.isdigit():
                raise ValueError("Destination channel must be a numeric Discord channel ID.")
            role_ids = [part.strip() for part in roles.split(",") if part.strip()]
            if any(not role.isdigit() for role in role_ids):
                raise ValueError("Role IDs must be numeric and comma separated.")
            template.update(destination_channel_id=int(channel) if channel else None, role_ids=[int(role) for role in role_ids])
    except ValueError as exc:
        await _modal_source(ctx, message_editor(draft, ref[1], ref[2], str(exc))); return
    saved = await _save_campaign(mongo, draft, campaign)
    await _modal_source(ctx, message_editor(saved, ref[1], ref[2], "Draft saved."))


@register_action("cwl_submit_text", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_text(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _submit_message(ctx, action_id, mongo, "text")


@register_action("cwl_image_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_image(
    ctx: Any,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    media: MediaStore = lightbulb.di.INJECTED,
    **_: Any,
):
    """Consume the narrowly scoped native file upload after acknowledging it."""
    interaction = ctx.interaction
    # Acknowledge before Mongo/R2 work. cwl_media then waits one event-loop turn
    # if the raw gateway payload is still racing the typed modal event.
    await _ack_modal(ctx)
    ref = _parse_ref(action_id, 3)
    if not ref:
        await interaction.edit_initial_response(components=error_panel("This editor panel is out of date."), **NO_MENTIONS); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await interaction.edit_initial_response(components=error_panel(problem), **NO_MENTIONS); return
    target = {"message_id": ref[1], "audience": ref[2]}
    if target["message_id"] not in _campaign(draft).get("messages", {}) or target["audience"] not in AUDIENCES:
        await interaction.edit_initial_response(components=await panel(draft, "messages", "Choose Upload replacement again before uploading."), **NO_MENTIONS); return
    try:
        url = await cwl_media.upload_from_modal(
            interaction, media, guild_id=int(draft["guild_id"]),
            message_id=str(target["message_id"]), audience=str(target["audience"]),
        )
    except MediaStoreError as exc:
        await interaction.edit_initial_response(components=message_editor(draft, target["message_id"], target["audience"], str(exc)), **NO_MENTIONS); return
    campaign = _campaign(draft)
    _template(campaign, str(target["message_id"]), str(target["audience"]))["media_url"] = url
    saved = await _save_campaign(mongo, draft, campaign)
    await interaction.edit_initial_response(components=message_editor(saved, target["message_id"], target["audience"], "Artwork uploaded to this draft."), **NO_MENTIONS)


@register_action("cwl_submit_links", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_links(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _submit_message(ctx, action_id, mongo, "links")


@register_action("cwl_submit_delivery", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_delivery(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _submit_message(ctx, action_id, mongo, "delivery")


@register_action("cwl_toggle", preload_state=False)
@lightbulb.di.with_di
async def toggle(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    campaign = _campaign(draft); template = _template(campaign, ref[1], ref[2])
    template["enabled"] = not (template.get("enabled") is not False)
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, ref[1], ref[2], "Message enabled." if template["enabled"] else "Message disabled.")


@register_action("cwl_copy_text", preload_state=False)
@lightbulb.di.with_di
async def copy_text(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    target = "lazy" if ref[2] == "main" else "main"
    campaign = _campaign(draft)
    source, destination = _template(campaign, ref[1], ref[2]), _template(campaign, ref[1], target)
    destination["title"], destination["body"] = source["title"], source["body"]
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, ref[1], target, f"Copied {ref[2].title()} text into the {target.title()} draft. Links and delivery settings stayed in place.")


def _duplicate_key(campaign: dict, source: str) -> str:
    # Longest action prefix plus token/key/audience stays below Discord's
    # 100-character custom-id ceiling.
    base = re.sub(r"[^a-z0-9_-]+", "-", source.lower().replace(":", "-"))[:30].strip("-") or "reminder"
    while True:
        key = f"{base}-{uuid.uuid4().hex[:6]}"
        if key not in campaign.get("messages", {}):
            return key


@register_action("cwl_duplicate_message", preload_state=False)
@lightbulb.di.with_di
async def duplicate_message(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    campaign = _campaign(draft)
    if len(campaign.get("messages", {})) >= 12:
        return message_editor(draft, ref[1], ref[2], "You can have up to 12 messages. Remove one before adding another.")
    key = _duplicate_key(campaign, ref[1])
    source = copy.deepcopy(campaign["messages"][ref[1]])
    source["label"] = f"{source.get('label', _message_label(ref[1]))} copy"
    source["schedule"] = {"mode": "manual"}
    campaign["messages"][key] = source
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, key, ref[2], "Created an independent reminder. Set its timing before applying.")


@register_action("cwl_add_reminder", preload_state=False)
@lightbulb.di.with_di
async def add_reminder(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    campaign = _campaign(draft)
    if campaign.get("reminder_sequence", {}).get("enabled"):
        return sequence_panel(draft, "Open Reminders to change how many messages are sent.")
    if len(campaign.get("messages", {})) >= 12:
        return await panel(draft, "messages", "You can have up to 12 messages. Remove one before adding another.")
    key = _duplicate_key(campaign, "reminder")
    source = copy.deepcopy(campaign["messages"]["signup"])
    source.update(label="New reminder", schedule={"mode": "manual"})
    campaign["messages"][key] = source
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, key, "main", "Created a new reminder from the signup message. Edit its text and schedule.")


@register_action("cwl_share_image", preload_state=False)
@lightbulb.di.with_di
async def share_image(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    target = "lazy" if ref[2] == "main" else "main"
    campaign = _campaign(draft)
    _template(campaign, ref[1], target)["media_url"] = _template(campaign, ref[1], ref[2]).get("media_url", "")
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, ref[1], ref[2], f"{ref[2].title()} artwork is now shared with {target.title()}.")


@register_action("cwl_reset_image", preload_state=False)
@lightbulb.di.with_di
async def reset_image(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    try:
        default_url = cwl_campaign.default_campaign()["messages"][ref[1]]["variants"][ref[2]]["media_url"]
    except KeyError:
        return message_editor(draft, ref[1], ref[2], "This custom message has no native default artwork.")
    campaign = _campaign(draft)
    _template(campaign, ref[1], ref[2])["media_url"] = default_url
    saved = await _save_campaign(mongo, draft, campaign)
    return message_editor(saved, ref[1], ref[2], "Native artwork restored in this draft.")


@register_action("cwl_manual", preload_state=False)
@lightbulb.di.with_di
async def queue_manual(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    await cwl_campaign.queue_manual_occurrence(
        mongo, int(draft["guild_id"]), ref[1], ref[2], _cycle(draft), int(ctx.user.id)
    )
    return message_editor(draft, ref[1], ref[2], "Roster queued with saved text and artwork.")


@register_action("cwl_preview", preload_state=False)
@lightbulb.di.with_di
async def preview(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    try:
        campaign = _campaign(draft)
        preview_cycle = _scope_cycle(draft)
        rendered = cwl_campaign.render_message({
            "campaign": campaign, "cycle": preview_cycle,
            "deadline": cwl_campaign.signup_deadline(campaign, preview_cycle).isoformat(),
        }, ref[1], ref[2], preview=True)
        if inspect.isawaitable(rendered):
            rendered = await rendered
    except (TypeError, ValueError) as exc:
        return message_editor(draft, ref[1], ref[2], f"Preview unavailable: {exc}")
    # The renderer remains the source of truth. This small inert navigation card
    # sits after it and has no effect on the exact campaign post being reviewed.
    return list(rendered) + [hikari.impl.ContainerComponentBuilder(
        accent_color=ACCENT,
        components=[
            _button_group(
                (f"cwl_preview:{_draft_token(draft)}|{ref[1]}|main", "Main", hikari.ButtonStyle.PRIMARY),
                (f"cwl_preview:{_draft_token(draft)}|{ref[1]}|lazy", "Lazy", hikari.ButtonStyle.PRIMARY),
                (f"cwl_open_message:{action_id}", "Back to editor", hikari.ButtonStyle.SECONDARY),
            ),
        ],
    )]


@register_action("cwl_open_message", preload_state=False)
@lightbulb.di.with_di
async def open_message(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref:
        return error_panel("This editor panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    return error_panel(problem) if problem else message_editor(draft, ref[1], ref[2])


@register_action("cwl_schedule_mode", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_schedule(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 2)
    if not ref:
        await _modal_source(ctx, error_panel("This editor panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    if _is_sequence_reminder(ref[1]) and _campaign(draft).get("reminder_sequence", {}).get("enabled"):
        await _modal_source(ctx, sequence_panel(draft, "Numbered reminders are timed by the reminder sequence. Edit the sequence instead of an individual time.")); return
    values = getattr(ctx.interaction, "values", ())
    if len(values) != 1 or values[0] not in {"monthly", "after_open", "before_close", "specific", "legacy_chain", "manual"}:
        await _modal_source(ctx, schedule_editor(draft, ref[1], "Choose a timing option.")); return
    mode = values[0]
    schedule = _schedule(_campaign(draft), ref[1])
    if mode == "monthly":
        await _modal_source(ctx, monthly_editor(draft, ref[1])); return
    if mode == "manual":
        campaign = _campaign(draft); _schedule(campaign, ref[1]).clear(); _schedule(campaign, ref[1])["mode"] = "manual"
        (campaign.get("schedules") or {}).pop(ref[1], None)
        saved, notice = await _save_timing(ctx, mongo, draft, campaign)
        target = await panel(saved, "schedule", notice) if ref[1] == "signup" else schedule_editor(saved, ref[1], notice)
        await _modal_source(ctx, target); return
    await ctx.respond_with_modal(
        title=cwl_forms.schedule_form(schedule | {"mode": mode})[0][:45], custom_id=f"cwl_submit_schedule:{action_id}|{mode}",
        components=cwl_forms.schedule_form(schedule | {"mode": mode})[1],
    )


@register_action("cwl_monthly_choice", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def choose_monthly(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3)
    if not ref or ref[2] not in {"day", "end"}:
        await _modal_source(ctx, error_panel("Choose a monthly date option.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    if ref[1] not in _campaign(draft).get("messages", {}):
        await _modal_source(ctx, error_panel("Choose an existing CWL message.")); return
    mode = "monthly_day" if ref[2] == "day" else "monthly_end"
    title, fields = cwl_forms.schedule_form(_schedule(_campaign(draft), ref[1]) | {"mode": mode})
    await ctx.respond_with_modal(title=title, custom_id=f"cwl_submit_schedule:{ref[0]}|{ref[1]}|{ref[2]}", components=fields)


@register_action("cwl_submit_schedule", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_schedule(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _ack_modal(ctx)
    ref = _parse_ref(action_id, 3)
    legacy = False
    if ref is None:
        ref = _parse_ref(action_id, 2)
        legacy = ref is not None
    if not ref:
        await _modal_source(ctx, error_panel("This editor panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    if _is_sequence_reminder(ref[1]) and _campaign(draft).get("reminder_sequence", {}).get("enabled"):
        await _modal_source(ctx, sequence_panel(draft, "Numbered reminders are timed by the reminder sequence. Edit the sequence instead of an individual time.")); return
    mode = _modal_value(ctx, "mode").strip() if legacy else ref[2]
    mode = {"day": "monthly_day", "end": "monthly_end"}.get(mode, mode)
    values = {item.custom_id: str(item.value or "") for row in ctx.interaction.components for item in row}
    if legacy:
        raw = _modal_value(ctx, "value").strip()
        if mode == "monthly":
            pieces = raw.split(maxsplit=1)
            values = {"day": pieces[0] if pieces else "", "time": pieces[1] if len(pieces) == 2 else ""}
        elif mode == "specific" and "T" in raw:
            values = {"date": raw[:10], "time": raw[11:16]}
        elif mode in {"before_close", "after_open", "legacy_chain"}:
            values = {"amount": raw, "unit": "minutes"}
    campaign = _campaign(draft); previous = _schedule(campaign, ref[1])
    try:
        schedule = cwl_forms.parse_schedule_fields(mode, values, previous=previous)
    except ValueError as exc:
        await _modal_source(ctx, schedule_editor(draft, ref[1], str(exc))); return
    if mode == "legacy_chain":
        schedule["after"] = "signup" if ref[1] == "reminder:1" else previous.get("after", "signup")
    campaign["messages"][ref[1]]["schedule"] = schedule
    (campaign.get("schedules") or {}).pop(ref[1], None)
    saved, notice = await _save_timing(ctx, mongo, draft, campaign)
    target = await panel(saved, "schedule", notice) if ref[1] == "signup" else schedule_editor(saved, ref[1], notice)
    await _modal_source(ctx, target)


@register_action("cwl_settings", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def edit_settings(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    campaign = _campaign(draft)
    mode = cwl_forms.deadline_mode(campaign.get("signup_deadline", {}))
    await ctx.respond_with_modal(
        title="CWL signup deadline", custom_id=f"cwl_submit_settings:{action_id}|{mode}",
        components=cwl_forms.deadline_form(campaign.get("signup_deadline", {}), str(campaign.get("timezone") or "America/New_York"), mode=mode),
    )


@register_action("cwl_deadline_mode", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def choose_deadline_mode(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    values = getattr(ctx.interaction, "values", ())
    if len(values) != 1 or values[0] not in {"month_end", "day", "specific"}:
        await _modal_source(ctx, await panel(draft, "settings", "Choose a deadline rule.")); return
    campaign = _campaign(draft); mode = values[0]
    await ctx.respond_with_modal(
        title="CWL signup deadline", custom_id=f"cwl_submit_settings:{action_id}|{mode}",
        components=cwl_forms.deadline_form(campaign.get("signup_deadline", {}), str(campaign.get("timezone") or "America/New_York"), mode=mode),
    )


@register_action("cwl_submit_settings", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit_settings(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    await _ack_modal(ctx)
    ref = _parse_ref(action_id, 2)
    legacy = False
    if ref is None:
        ref = _parse_ref(action_id, 1)
        legacy = ref is not None
    if not ref:
        await _modal_source(ctx, error_panel("This settings panel is out of date.")); return
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        await _modal_source(ctx, error_panel(problem)); return
    values = {item.custom_id: str(item.value or "") for row in ctx.interaction.components for item in row}
    if legacy or "deadline" in values:
        raw = _modal_value(ctx, "deadline").strip()
        match = re.fullmatch(r"end-(\d+)\s+(\d{1,2}:\d{2})", raw, re.I)
        if match:
            mode, values = "month_end", {"offset_days": match[1], "time": match[2], "timezone": _modal_value(ctx, "timezone")}
        else:
            await _modal_source(ctx, await panel(draft, "settings", "Choose a deadline rule.")); return
    else:
        mode = ref[1]
    try:
        rule, timezone = cwl_forms.parse_deadline_fields(mode, values)
    except ValueError as exc:
        await _modal_source(ctx, await panel(draft, "settings", str(exc))); return
    campaign = _campaign(draft); campaign.update(signup_deadline=rule, timezone=timezone)
    try:
        saved, notice = await _save_timing(ctx, mongo, draft, campaign)
    except (TypeError, ValueError) as exc:
        await _modal_source(ctx, await panel(draft, "schedule", f"Settings were not saved: {exc}")); return
    await _modal_source(ctx, await panel(saved, "schedule", notice))


async def _apply_scope(ctx: Any, mongo: MongoClient, draft: dict, scope: str) -> list:
    token = _draft_token(draft)
    # Always set scope: a previous failed defaults confirmation may have left
    # the durable draft in defaults mode when the editor switches back to month.
    await cwl_campaign.patch_draft(mongo, token, {"scope": scope})
    result = await cwl_campaign.apply_draft(mongo, token, int(ctx.user.id), expected_revision=draft.get("base_revision"), require_future_signup=True)
    refreshed = await cwl_campaign.new_draft(
        mongo, int(draft["guild_id"]), int(ctx.user.id),
        cycle=_scope_cycle(draft, scope), scope="defaults" if scope == "defaults" else "cycle",
    )
    notice = "Settings saved for future months." if scope == "defaults" else "Settings saved. Messages already sent will not be sent again."
    if isinstance(result, dict) and result.get("schedule_sync_pending"):
        notice += " The schedule sync is pending and will retry automatically."
    return await panel(
        refreshed, "settings",
        notice,
        mongo=mongo,
    )


@register_action("cwl_apply_review", preload_state=False)
@lightbulb.di.with_di
async def review_apply(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 3) or _parse_ref(action_id, 2)
    if not ref or ref[1] not in {"cycle", "defaults"} or (len(ref) == 3 and ref[2] not in {"overview", "schedule"}):
        return error_panel("This apply review is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    affected_cycle = _scope_cycle(draft, ref[1])
    try:
        # Let staff edit opening and closing in either order, but require a
        # complete resolved plan before a reviewed change can be applied.
        cwl_campaign.resolve_schedule(_campaign(draft), affected_cycle)
    except (TypeError, ValueError) as exc:
        return await panel(draft, "schedule", f"Review is not ready: fix the reminder timing first. {exc}", mongo=mongo)
    if ref[1] == "defaults":
        before = await _saved_defaults_campaign(mongo, int(draft["guild_id"]))
    else:
        before = (await cwl_campaign.load_campaign(mongo, int(draft["guild_id"]), _cycle(draft)))["campaign"]
    summary = cwl_review.change_summary(before, _campaign(draft), affected_cycle)
    review_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": review_id, "type": "cwl_apply_review", "user_id": int(ctx.user.id),
        "guild_id": int(draft["guild_id"]), "draft_id": _draft_token(draft),
        "draft_updated_at": draft.get("updated_at"), "scope": ref[1], "affected_cycle": affected_cycle,
    }, ttl=timedelta(minutes=10))
    scope_label = f"future months, starting {affected_cycle}. Months you edited separately keep their own settings" if ref[1] == "defaults" else f"messages not yet sent for {_cycle(draft)}"
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content=f"## Review CWL changes\nApplies to **{scope_label}**."),
        hikari.impl.TextDisplayComponentBuilder(content=summary),
        _button_group(
            (f"cwl_apply_confirm:{review_id}", "Save changes", hikari.ButtonStyle.SUCCESS),
            (f"cwl_save_options:{_draft_token(draft)}|{ref[2] if len(ref) == 3 else 'schedule'}", "Back", hikari.ButtonStyle.SECONDARY),
        ),
    ])]


@register_action("cwl_apply_confirm", preload_state=False)
@lightbulb.di.with_di
async def confirm_apply(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    state = await get_state(mongo, action_id)
    if not state or state.get("type") != "cwl_apply_review":
        return error_panel("This apply review expired. Review the draft again.")
    if not can_edit(ctx) or int(state.get("user_id", 0)) != int(ctx.user.id) or int(state.get("guild_id", 0)) != int(ctx.interaction.guild_id):
        return error_panel("Open your own CWL dashboard to apply changes.")
    draft, problem = await _load(ctx, mongo, str(state["draft_id"]))
    if problem:
        return error_panel(problem)
    if draft.get("updated_at") != state.get("draft_updated_at"):
        return await panel(draft, "settings", "The draft changed after this review. Review it again before applying.", mongo=mongo)
    try:
        return await _apply_scope(ctx, mongo, draft, str(state["scope"]))
    except (RuntimeError, ValueError) as exc:
        return await panel(draft, "settings", f"Changes were not applied: {exc}", mongo=mongo)


@register_action("cwl_discard_review", preload_state=False)
@lightbulb.di.with_di
async def review_discard(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    review_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": review_id, "type": "cwl_discard_review", "user_id": int(ctx.user.id),
        "guild_id": int(draft["guild_id"]), "draft_id": _draft_token(draft),
        "draft_updated_at": draft.get("updated_at"), "cycle": _cycle(draft),
    }, ttl=timedelta(minutes=10))
    return [hikari.impl.ContainerComponentBuilder(accent_color=ERROR, components=[
        hikari.impl.TextDisplayComponentBuilder(content="## Discard your changes?\nThis removes your edits and opens the settings the bot is currently using."),
        _button_group(
            (f"cwl_discard_confirm:{review_id}", "Discard and reload", hikari.ButtonStyle.DANGER),
            (f"cwl_tab:{_draft_token(draft)}|settings", "Keep editing", hikari.ButtonStyle.SECONDARY),
        ),
    ])]


@register_action("cwl_discard_confirm", preload_state=False)
@lightbulb.di.with_di
async def confirm_discard(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    state = await get_state(mongo, action_id)
    if not state or state.get("type") != "cwl_discard_review":
        return error_panel("This confirmation expired. Open Schedule, then More options, to try again.")
    if not can_edit(ctx) or int(state.get("user_id", 0)) != int(ctx.user.id) or int(state.get("guild_id", 0)) != int(ctx.interaction.guild_id):
        return error_panel("Open your own CWL dashboard to discard a draft.")
    draft, problem = await _load(ctx, mongo, str(state["draft_id"]))
    if problem:
        return error_panel(problem)
    if draft.get("updated_at") != state.get("draft_updated_at"):
        return await panel(draft, "settings", "The draft changed after this review. Start discard review again.", mongo=mongo)
    # Resolve the full document id only after rechecking ownership; the token in
    # the button is never used as a broad delete target.
    await mongo.bot_config.delete_one({"_id": draft["_id"]})
    fresh = await cwl_campaign.new_draft(mongo, int(draft["guild_id"]), int(ctx.user.id), cycle=str(state["cycle"]))
    return await panel(fresh, "settings", "Discarded the old draft and loaded the current saved configuration.", mongo=mongo)


# Compatibility helpers for programmatic callers. Dashboard buttons always use
# the reviewed confirmation path above.
async def apply_cycle(ctx: Any, action_id: str, mongo: MongoClient):
    draft, problem = await _load(ctx, mongo, action_id)
    return error_panel(problem) if problem else await _apply_scope(ctx, mongo, draft, "cycle")


async def apply_defaults(ctx: Any, action_id: str, mongo: MongoClient):
    draft, problem = await _load(ctx, mongo, action_id)
    return error_panel(problem) if problem else await _apply_scope(ctx, mongo, draft, "defaults")


@register_action("cwl_pause", preload_state=False)
@lightbulb.di.with_di
async def pause(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    draft, problem = await _load(ctx, mongo, action_id)
    if problem:
        return error_panel(problem)
    campaign = _campaign(draft)
    live = await cwl_campaign.set_paused(
        mongo, int(draft["guild_id"]), not bool(campaign.get("paused")), cycle=_cycle(draft), user_id=int(ctx.user.id)
    )
    campaign["paused"] = not bool(campaign.get("paused"))
    # Only rebase an immediately preceding revision. If somebody else already
    # changed the campaign, preserve this draft's stale base so Apply rejects
    # rather than allowing pause to silently defeat the CAS protection.
    prior_revision = int(draft.get("cycle_base_revision", draft.get("base_revision", 0)))
    patch = {"campaign": campaign}
    rebased = prior_revision == int(live["revision"]) - 1
    if rebased:
        patch.update(cycle_base_revision=live["revision"], base_revision=live["revision"], recurring_base_version=live.get("recurring_version"))
    saved = await cwl_campaign.patch_draft(mongo, _draft_token(draft), patch)
    notice = "Automatic messages resumed." if not campaign["paused"] else "Automatic messages paused. Resume them when you are ready."
    if not rebased:
        notice += " This draft was already stale; reload the saved version before applying other edits."
    return await panel(saved, "overview", notice, mongo=mongo)


@register_action("cwl_skip", preload_state=False)
@lightbulb.di.with_di
async def skip(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _split_ref(action_id)
    if not ref:
        return error_panel("This dashboard panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    await cwl_campaign.skip_occurrence(mongo, int(draft["guild_id"]), ref[1], cycle=_cycle(draft), user_id=int(ctx.user.id))
    return await panel(draft, "overview", "Post skipped.", mongo=mongo)


@register_action("cwl_retry", preload_state=False)
@register_action("cwl_restore", preload_state=False)
@register_action("cwl_update_start", preload_state=False)
@register_action("cwl_update_confirm", preload_state=False)
async def retired_history_action(ctx: Any, action_id: str, **_: Any):
    """Old Discord controls must not restore settings or publish messages."""
    return error_panel("This control was removed. Open `/cwl dashboard`.")


loader.listener(hikari.ShardPayloadEvent)(cwl_media.capture_upload_payload)
loader.command(cwl)
