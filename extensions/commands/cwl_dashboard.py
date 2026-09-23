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
from utils import cwl_publishing
from utils import cwl_forms
from utils import cwl_review


loader = lightbulb.Loader()
cwl = lightbulb.Group(
    "cwl", "Configure CWL announcements and reminders",
    default_member_permissions=hikari.Permissions.MANAGE_GUILD,
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
        permissions & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD)
    )


async def require_editor(ctx: Any) -> bool:
    if can_edit(ctx):
        return True
    await ctx.respond("You need Manage Server permission to manage CWL announcements.", ephemeral=True)
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
        return None, "You need Manage Server permission to manage CWL announcements."
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
    for tab, label in (("overview", "Overview"), ("messages", "Messages"), ("schedule", "Schedule"), ("settings", "Settings"), ("history", "History")):
        row.add_interactive_button(
            hikari.ButtonStyle.PRIMARY if tab == active else hikari.ButtonStyle.SECONDARY,
            f"cwl_tab:{draft_id}|{tab}" + ("|active" if tab == active else ""),
            label=label, is_disabled=tab == active,
        )
    return row


def error_panel(message: str) -> list:
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=ERROR,
        components=[hikari.impl.TextDisplayComponentBuilder(content=f"## CWL Dashboard\n{message}")],
    )]


def _header(draft: dict, tab: str, notice: str | None = None) -> list:
    campaign = _campaign(draft)
    paused = "⏸ Paused" if campaign.get("paused") else "● Active"
    rows: list = [
        hikari.impl.TextDisplayComponentBuilder(content="## <:CWL:1399013745598009375> CWL Campaign"),
        hikari.impl.TextDisplayComponentBuilder(
            content=f"Cycle: **{_cycle(draft)}** · {paused} · Timezone: **{campaign.get('timezone', 'America/New_York')}**"
        ),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    rows.append(_tabs(_draft_token(draft), tab))
    return rows


async def panel(draft: dict, tab: str = "overview", notice: str | None = None, mongo: MongoClient | None = None) -> list:
    """Render a compact mobile-friendly editor panel from a durable draft."""
    campaign = _campaign(draft)
    draft_id = _draft_token(draft)
    rows = _header(draft, tab, notice)

    if tab == "overview":
        live = await cwl_campaign.load_campaign(mongo, int(draft["guild_id"]), _cycle(draft)) if mongo is not None else None
        occurrences = (live or {}).get("schedule") or cwl_campaign.resolve_schedule(campaign, _cycle(draft), now=utcnow())
        sent = {item.get("occurrence_id") for item in (live or {}).get("deliveries", ()) if item.get("status") == "sent"}
        skipped = set((live or {}).get("skipped", ()))
        now = utcnow()
        def future(entry):
            value = entry.get("run_at")
            if not value:
                return False
            try:
                return datetime.fromisoformat(value) > now
            except ValueError:
                return False
        pending = [entry for entry in occurrences if entry.get("id") not in sent | skipped and future(entry)]
        next_item = pending[0] if pending else None
        next_text = "No pending scheduled message."
        if next_item:
            next_text = f"**{_message_label(str(next_item.get('message_id', next_item.get('message_key', 'message'))))}** · {_short(next_item.get('run_at', next_item.get('at', 'manual')))}"
        rows.extend([
            hikari.impl.SeparatorComponentBuilder(divider=True),
            hikari.impl.TextDisplayComponentBuilder(content=f"### Signup deadline\n{_deadline(campaign)}"),
            hikari.impl.TextDisplayComponentBuilder(content=f"### Next delivery\n{next_text}"),
            _button(f"cwl_pause:{draft_id}", "Resume campaign" if campaign.get("paused") else "Pause campaign", style=hikari.ButtonStyle.DANGER if not campaign.get("paused") else hikari.ButtonStyle.SUCCESS),
        ])
        if next_item and next_item.get("id"):
            rows.append(_button(f"cwl_skip:{draft_id}|{next_item['id']}", "Skip next occurrence", style=hikari.ButtonStyle.SECONDARY))

    elif tab == "messages":
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="### Messages\nChoose a message and its Main or Lazy version. Text, artwork, buttons, destination, and pings stay together."))
        menu_row = hikari.impl.MessageActionRowBuilder()
        menu = menu_row.add_text_menu(
            f"cwl_message:{draft_id}", min_values=1, placeholder="Choose a message version"
        )
        for key, label in _message_items(campaign)[:12]:
            for audience in AUDIENCES:
                template = _template(campaign, key, audience)
                suffix = "disabled" if template.get("enabled") is False else _short(template.get("title") or template.get("body") or "Untitled", 45)
                menu.add_option(f"{label} · {audience.title()}", f"{key}|{audience}", description=suffix)
        rows.append(menu_row)
        rows.append(_button(f"cwl_add_reminder:{draft_id}", "Add reminder from signup", style=hikari.ButtonStyle.PRIMARY))
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="Changes are drafts until you apply them. Use Preview to see the scheduler's exact rendered post with pings suppressed."))

    elif tab == "schedule":
        rows.append(hikari.impl.TextDisplayComponentBuilder(content="### Schedule\nUse recognizable event-based timing. The resolved dates below follow this draft's timezone."))
        menu_row = hikari.impl.MessageActionRowBuilder()
        menu = menu_row.add_text_menu(
            f"cwl_schedule:{draft_id}", min_values=1, placeholder="Choose a message schedule"
        )
        for key, label in _message_items(campaign)[:25]:
            menu.add_option(label, key, description=_time_description(_schedule(campaign, key))[:100])
        rows.append(menu_row)
        try:
            occurrences = cwl_campaign.resolve_schedule(campaign, _cycle(draft), now=utcnow())[:5]
        except (TypeError, ValueError):
            occurrences = []
        if occurrences:
            lines = [f"• {_message_label(str(item.get('message_id', item.get('message_key', 'message'))))}: {_short(item.get('run_at', item.get('at', 'manual')))}" for item in occurrences]
            rows.append(hikari.impl.TextDisplayComponentBuilder(content="### Upcoming\n" + "\n".join(lines)))

    elif tab == "settings":
        deadline_row = hikari.impl.MessageActionRowBuilder()
        deadline_modes = deadline_row.add_text_menu(
            f"cwl_deadline_mode:{draft_id}", min_values=1, placeholder="Choose signup deadline rule"
        )
        active_deadline = cwl_forms.deadline_mode(campaign.get("signup_deadline", {}))
        for value, label in (("month_end", "Before month end"), ("day", "Day of month"), ("specific", "Specific date")):
            deadline_modes.add_option(label, value, is_default=value == active_deadline)
        rows.extend([
            hikari.impl.TextDisplayComponentBuilder(content=f"### Campaign settings\nSignup deadline: **{_deadline(campaign)}**\nTimezone: **{campaign.get('timezone', 'America/New_York')}**"),
            _button(f"cwl_settings:{draft_id}", "Edit deadline & timezone", style=hikari.ButtonStyle.PRIMARY),
            deadline_row,
            hikari.impl.TextDisplayComponentBuilder(content="### Apply changes\nThis month changes only unsent occurrences. Monthly defaults become the starting point for future CWL cycles."),
            _button(f"cwl_apply_review:{draft_id}|cycle", "Review this month", style=hikari.ButtonStyle.SUCCESS),
            _button(f"cwl_apply_review:{draft_id}|defaults", "Review monthly defaults", style=hikari.ButtonStyle.PRIMARY),
            hikari.impl.TextDisplayComponentBuilder(content="-# If another administrator saved CWL changes first, discard this draft and explicitly reload the current saved configuration."),
            _button(f"cwl_discard_review:{draft_id}", "Reload saved version", style=hikari.ButtonStyle.DANGER),
        ])

    elif tab == "history":
        history = campaign.get("history", draft.get("history", ()))
        if mongo is not None:
            history = await cwl_campaign.history(mongo, int(draft["guild_id"]), _cycle(draft), limit=25)
        if not isinstance(history, list) or not history:
            rows.append(hikari.impl.TextDisplayComponentBuilder(content="### Delivery history\nNo delivery attempts recorded for this cycle."))
        else:
            lines = []
            for item in history[:8]:
                state = "✓" if item.get("status") in {"sent", "success"} else "⚠"
                link = f" · [Post]({item['message_url']})" if item.get("message_url") else ""
                lines.append(f"{state} **{_message_label(str(item.get('message_id', item.get('message_key', 'message'))))}** · {_short(item.get('status', item.get('action', 'unknown')))} · {_short(item.get('at', item.get('created_at', '')))}{link}")
            rows.append(hikari.impl.TextDisplayComponentBuilder(content="### Delivery history\n" + "\n".join(lines)))
            failed = next((item for item in history if item.get("status") in {"failed", "error"} and item.get("occurrence_id")), None)
            if failed:
                rows.append(_button(f"cwl_retry:{draft_id}|{failed['occurrence_id']}", "Retry latest failed delivery", style=hikari.ButtonStyle.PRIMARY))
            published = next((item for item in history if item.get("status") == "sent" and item.get("occurrence_id")), None)
            if published:
                rows.append(_button(f"cwl_update_start:{draft_id}|{published['occurrence_id']}", "Update published post"))
            restorable = next((item for item in history if isinstance(item.get("revision"), int)), None)
            if restorable:
                rows.append(_button(f"cwl_restore:{draft_id}|{restorable['revision']}", f"Restore revision {restorable['revision']}"))

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
        placeholder="Choose delivery channel", min_values=1, max_values=1,
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
            (f"cwl_delivery:{ref}", "Delivery", hikari.ButtonStyle.SECONDARY),
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
            *((f"cwl_manual:{ref}", "Queue roster", hikari.ButtonStyle.SUCCESS),) if key == "roster" else (),
            (f"cwl_tab:{_draft_token(draft)}|messages", "Back", hikari.ButtonStyle.SECONDARY),
        ),
    ])
    if template.get("media_url"):
        rows.insert(5, hikari.impl.MediaGalleryComponentBuilder(items=[
            hikari.impl.MediaGalleryItemBuilder(media=str(template["media_url"]))
        ]))
        rows.insert(5, hikari.impl.TextDisplayComponentBuilder(content="### Current image in this draft"))
        rows.insert(7, hikari.impl.TextDisplayComponentBuilder(
            content="-# Restore default image brings back the original artwork. Draft changes stay private until reviewed and applied."
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
        draft = await cwl_campaign.find_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=self.cycle)
        resumed = draft is not None
        if draft is None:
            draft = await cwl_campaign.new_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=self.cycle)
        await ctx.respond(components=await panel(draft, "overview", "Resumed your saved CWL draft." if resumed else None, mongo=mongo), ephemeral=True, **NO_MENTIONS)


async def open_dashboard(ctx: Any, mongo: MongoClient, *, bot: Any = None, cycle: str | None = None) -> dict | None:
    """Open a CWL draft from another already-deferred private dashboard panel."""
    if not await require_editor(ctx):
        return None
    draft = await cwl_campaign.find_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=cycle)
    resumed = draft is not None
    if draft is None:
        draft = await cwl_campaign.new_draft(mongo, int(ctx.interaction.guild_id), int(ctx.user.id), cycle=cycle)
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
    return schedule_editor(draft, key)


def schedule_editor(draft: dict, key: str, notice: str | None = None) -> list:
    campaign = _campaign(draft)
    schedule = _schedule(campaign, key)
    rows = _header(draft, "schedule", notice)
    rows.extend([
        hikari.impl.SeparatorComponentBuilder(divider=True),
        hikari.impl.TextDisplayComponentBuilder(content=f"### {_message_label(key)}\n**{_time_description(schedule)}**\nMode: `{schedule.get('mode', 'manual')}`"),
        hikari.impl.TextDisplayComponentBuilder(content="Choose how this message is timed. The form uses calendar dates and ordinary minutes, hours, or days."),
        _button(f"cwl_tab:{_draft_token(draft)}|schedule", "Back"),
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
        _button(f"cwl_tab:{_draft_token(draft)}|schedule", "Back"),
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
        title = "Edit CWL delivery"
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
    rows.append(_button(f"cwl_open_message:{ref}", "Back"))
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
        _button(f"cwl_links:{action_id}", "Back"),
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
        return message_editor(draft, ref[1], ref[2], "This campaign already has 12 messages, the dashboard's one-screen limit.")
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
    if len(campaign.get("messages", {})) >= 12:
        return await panel(draft, "messages", "This campaign already has 12 messages, the dashboard's one-screen limit.")
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
    return message_editor(draft, ref[1], ref[2], "Roster delivery queued. It uses the applied campaign template.")


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
        rendered = cwl_campaign.render_message({
            "campaign": campaign, "cycle": _cycle(draft),
            "deadline": cwl_campaign.signup_deadline(campaign, _cycle(draft)).isoformat(),
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
    values = getattr(ctx.interaction, "values", ())
    if len(values) != 1 or values[0] not in {"monthly", "after_open", "before_close", "specific", "legacy_chain", "manual"}:
        await _modal_source(ctx, schedule_editor(draft, ref[1], "Choose a timing option.")); return
    mode = values[0]
    schedule = _schedule(_campaign(draft), ref[1])
    if mode == "monthly":
        await _modal_source(ctx, monthly_editor(draft, ref[1])); return
    if mode == "manual":
        campaign = _campaign(draft); _schedule(campaign, ref[1]).clear(); _schedule(campaign, ref[1])["mode"] = "manual"
        saved = await _save_campaign(mongo, draft, campaign)
        await _modal_source(ctx, schedule_editor(saved, ref[1], "This message is now manual.")); return
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
    saved = await _save_campaign(mongo, draft, campaign)
    await _modal_source(ctx, schedule_editor(saved, ref[1], "Schedule draft saved."))


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
    saved = await _save_campaign(mongo, draft, campaign)
    await _modal_source(ctx, await panel(saved, "settings", "Settings draft saved."))


async def _apply_scope(ctx: Any, mongo: MongoClient, draft: dict, scope: str) -> list:
    token = _draft_token(draft)
    # Always set scope: a previous failed defaults confirmation may have left
    # the durable draft in defaults mode when the editor switches back to month.
    await cwl_campaign.patch_draft(mongo, token, {"scope": scope})
    result = await cwl_campaign.apply_draft(mongo, token, int(ctx.user.id), expected_revision=draft.get("base_revision"))
    refreshed = await cwl_campaign.new_draft(mongo, int(draft["guild_id"]), int(ctx.user.id), cycle=_cycle(draft))
    notice = "Monthly defaults saved for future CWL cycles." if scope == "defaults" else "This month's unsent messages were updated."
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
    ref = _parse_ref(action_id, 2)
    if not ref or ref[1] not in {"cycle", "defaults"}:
        return error_panel("This apply review is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    if ref[1] == "defaults":
        saved = await mongo.bot_config.find_one({"_id": cwl_campaign.defaults_id(int(draft["guild_id"]))})
        before = cwl_campaign._deep_merge(cwl_campaign.default_campaign(), saved.get("campaign") if saved else None)
    else:
        before = (await cwl_campaign.load_campaign(mongo, int(draft["guild_id"]), _cycle(draft)))["campaign"]
    summary = cwl_review.change_summary(before, _campaign(draft), _cycle(draft))
    review_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": review_id, "type": "cwl_apply_review", "user_id": int(ctx.user.id),
        "guild_id": int(draft["guild_id"]), "draft_id": _draft_token(draft),
        "draft_updated_at": draft.get("updated_at"), "scope": ref[1],
    }, ttl=timedelta(minutes=10))
    scope_label = "monthly defaults" if ref[1] == "defaults" else f"unsent { _cycle(draft) } occurrences"
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content=f"## Review CWL changes\nApplies to **{scope_label}**."),
        hikari.impl.TextDisplayComponentBuilder(content=summary),
        _button_group(
            (f"cwl_apply_confirm:{review_id}", "Apply these changes", hikari.ButtonStyle.SUCCESS),
            (f"cwl_tab:{_draft_token(draft)}|settings", "Back", hikari.ButtonStyle.SECONDARY),
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
        hikari.impl.TextDisplayComponentBuilder(content="## Discard CWL draft?\nThis permanently discards your unsaved CWL edits and opens the currently saved campaign. It will not merge or overwrite another administrator's work."),
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
        return error_panel("This discard review expired. Start it again from Settings.")
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
        patch.update(cycle_base_revision=live["revision"], base_revision=live["revision"])
    saved = await cwl_campaign.patch_draft(mongo, _draft_token(draft), patch)
    notice = "Campaign resumed." if not campaign["paused"] else "Campaign paused. No future CWL delivery will run until resumed."
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
    return await panel(draft, "overview", "Occurrence skipped. It remains visible in delivery history.", mongo=mongo)


@register_action("cwl_retry", preload_state=False)
@lightbulb.di.with_di
async def retry(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _split_ref(action_id)
    if not ref:
        return error_panel("This dashboard panel is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    await cwl_campaign.retry_occurrence(mongo, int(draft["guild_id"]), ref[1], cycle=_cycle(draft), user_id=int(ctx.user.id))
    return await panel(draft, "history", "Retry queued. It will use the saved campaign template.", mongo=mongo)


@register_action("cwl_restore", preload_state=False)
@lightbulb.di.with_di
async def restore(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any):
    ref = _parse_ref(action_id, 2)
    if not ref or not ref[1].isdigit():
        return error_panel("This revision link is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    restored = await cwl_campaign.restore_revision(
        mongo, int(draft["guild_id"]), int(ref[1]), int(ctx.user.id), cycle=_cycle(draft), scope="cycle"
    )
    return await panel(restored, "settings", f"Revision {ref[1]} was restored into a new draft. Review and apply it when ready.")


@register_action("cwl_update_start", preload_state=False)
@lightbulb.di.with_di
async def start_post_update(
    ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any,
):
    ref = _split_ref(action_id)
    if not ref:
        return error_panel("This published-post link is out of date.")
    draft, problem = await _load(ctx, mongo, ref[0])
    if problem:
        return error_panel(problem)
    try:
        target = await cwl_publishing.prepare_post_update(
            mongo, bot, guild_id=int(draft["guild_id"]), cycle=_cycle(draft), occurrence_id=ref[1],
            user_id=int(ctx.user.id), draft_id=_draft_token(draft),
        )
    except (ValueError, hikari.HTTPError) as exc:
        return await panel(draft, "history", f"Post update unavailable: {exc}", mongo=mongo)
    state_id = uuid.uuid4().hex
    await insert_state(mongo, {
        "_id": state_id, "type": "cwl_post_update", "user_id": int(ctx.user.id),
        "guild_id": int(draft["guild_id"]), "draft_id": _draft_token(draft), "cycle": _cycle(draft),
        "occurrence_id": ref[1], "target": target,
    }, ttl=timedelta(minutes=10))
    return [hikari.impl.ContainerComponentBuilder(accent_color=ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content="### Update published CWL post\nThe live post was checked and fingerprinted. This will replace its content with the current draft, without sending pings."),
        _button(f"cwl_update_confirm:{state_id}", "Update published post", style=hikari.ButtonStyle.DANGER),
        _button(f"cwl_tab:{_draft_token(draft)}|history", "Cancel"),
    ])]


@register_action("cwl_update_confirm", preload_state=False)
@lightbulb.di.with_di
async def confirm_post_update(
    ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED, **_: Any,
):
    state = await get_state(mongo, action_id)
    if not state or state.get("type") != "cwl_post_update":
        return error_panel("This post-update review expired. Start it again from delivery history.")
    if not can_edit(ctx) or int(state.get("user_id", 0)) != int(ctx.user.id) or int(state.get("guild_id", 0)) != int(ctx.interaction.guild_id):
        return error_panel("Open your own CWL dashboard to update a published post.")
    draft, problem = await _load(ctx, mongo, str(state["draft_id"]))
    if problem:
        return error_panel(problem)
    try:
        link = await cwl_publishing.update_published_post(
            mongo, bot, guild_id=int(state["guild_id"]), cycle=str(state["cycle"]),
            occurrence_id=str(state["occurrence_id"]), user_id=int(ctx.user.id),
            draft_id=str(state["draft_id"]), target=state["target"],
        )
    except (ValueError, hikari.HTTPError) as exc:
        return await panel(draft, "history", f"Post update did not run: {exc}", mongo=mongo)
    return await panel(draft, "history", f"Published post updated: {link}", mongo=mongo)


loader.listener(hikari.ShardPayloadEvent)(cwl_media.capture_upload_payload)
loader.command(cwl)
