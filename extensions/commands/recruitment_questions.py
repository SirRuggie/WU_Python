"""Private editor for six reusable recruitment question messages."""

from __future__ import annotations

import copy
import re
import uuid
from datetime import timedelta
from typing import Any

import hikari
import lightbulb

from extensions.components import register_action
from utils.component_state import get_state, insert_state
from utils.constants import GOLD_ACCENT, RED_ACCENT
from utils.discord_file_upload import (
    FileUploadModalComponentBuilder,
    install_file_upload_capture,
    pop_file_upload,
)
from utils.media_store import MediaStore, MediaStoreError
from utils.mongo import MongoClient
from utils.url_safety import MAX_IMAGE_BYTES
from utils import recruit_question_content as content


loader = lightbulb.Loader()
TTL = timedelta(minutes=30)
NO_MENTIONS = {"user_mentions": False, "role_mentions": False, "mentions_everyone": False}
_STATE_FIELDS = ("user_id", "guild_id", "manage_token", "view", "variant", "template", "saved_template")
_HEX_COLOR = re.compile(r"#?[0-9a-fA-F]{6}\Z")

install_file_upload_capture()


def allowed(ctx: Any) -> bool:
    member = getattr(ctx, "member", None) or getattr(ctx.interaction, "member", None)
    permissions = getattr(member, "permissions", hikari.Permissions.NONE)
    return bool(permissions & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD))


def _identity(ctx: Any) -> tuple[int | None, int | None]:
    user_id = getattr(getattr(ctx, "user", None), "id", None)
    guild_id = getattr(getattr(ctx, "interaction", None), "guild_id", None)
    return (
        int(user_id) if user_id is not None else None,
        int(guild_id) if guild_id is not None else None,
    )


async def _state(ctx: Any, mongo: MongoClient, token: str, *, view: str | None = None) -> tuple[dict | None, str | None]:
    state = await get_state(mongo, token)
    if state is None:
        return None, "This editor expired. Run `/manage` again."
    user_id, guild_id = _identity(ctx)
    if user_id is None or guild_id is None or state.get("user_id") != user_id or state.get("guild_id") != guild_id:
        return None, "Open your own Recruitment Questions editor in this server."
    if not allowed(ctx):
        return None, "Manage Server permission is required to manage recruitment questions."
    if view is not None and state.get("view") != view:
        return None, "This editor panel is out of date. Open Recruitment Questions from `/manage`."
    return state, None


async def _new_state(mongo: MongoClient, **fields: Any) -> dict:
    state = {key: copy.deepcopy(value) for key, value in fields.items() if key in _STATE_FIELDS}
    state["_id"] = uuid.uuid4().hex
    await insert_state(mongo, state, ttl=TTL)
    return state


async def _next(mongo: MongoClient, state: dict, **changes: Any) -> dict:
    values = {key: state[key] for key in _STATE_FIELDS if key in state}
    values.update(changes)
    return await _new_state(mongo, **values)


async def _home_state(mongo: MongoClient, state: dict) -> dict:
    return await _new_state(
        mongo, user_id=state["user_id"], guild_id=state["guild_id"],
        manage_token=state["manage_token"], view="home",
    )


def _error(message: str) -> list:
    return [hikari.impl.ContainerComponentBuilder(
        accent_color=RED_ACCENT,
        components=[
            hikari.impl.TextDisplayComponentBuilder(content=f"## Recruitment Questions\n{message}"),
            hikari.impl.TextDisplayComponentBuilder(content="Run `/manage` to open a fresh private editor."),
        ],
    )]


def _buttons(*items: tuple[str, str, hikari.ButtonStyle, bool]) -> hikari.impl.MessageActionRowBuilder:
    row = hikari.impl.MessageActionRowBuilder()
    for custom_id, label, style, disabled in items:
        row.add_interactive_button(style, custom_id, label=label, is_disabled=disabled)
    return row


def _home(state: dict, notice: str | None = None) -> list:
    sid = state["_id"]
    selector = hikari.impl.MessageActionRowBuilder()
    menu = selector.add_text_menu(f"recruit_question_variant:{sid}", min_values=1, max_values=1, placeholder="Choose a recruitment message")
    for variant in content.VARIANTS:
        menu.add_option(content.VARIANT_LABELS[variant], variant)
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content="## Recruitment Questions"),
        hikari.impl.TextDisplayComponentBuilder(content="Edit the six reusable recruitment messages used by `/recruit questions`."),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    rows.extend([
        selector,
        hikari.impl.TextDisplayComponentBuilder(content="-# Changes affect future posts only after you save."),
        _buttons((f"manage_home:{state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False)),
    ])
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLD_ACCENT, components=rows)]


def _dirty(state: dict) -> bool:
    return state.get("template") != state.get("saved_template")


def _editor(state: dict, notice: str | None = None) -> list:
    variant, sid, template = state["variant"], state["_id"], state["template"]
    selector = hikari.impl.MessageActionRowBuilder()
    menu = selector.add_text_menu(f"recruit_question_block:{sid}", min_values=1, max_values=1, placeholder="Choose a text block")
    for index, label in enumerate(content.BLOCK_LABELS[variant]):
        menu.add_option(label, str(index))
    native_footer = content.default_template(variant)["footer_url"]
    footer_status = "No footer artwork" if native_footer is None else ("Original artwork" if template["footer_url"] == native_footer else "Custom artwork")
    rows = [
        hikari.impl.TextDisplayComponentBuilder(content=f"## {content.VARIANT_LABELS[variant]}"),
        hikari.impl.TextDisplayComponentBuilder(content=f"{'Unsaved changes' if _dirty(state) else 'Saved'} · {len(template['sections'])} text blocks · {footer_status}"),
        hikari.impl.TextDisplayComponentBuilder(content="Use `{recruit}` and `{recruiter}` for live mentions. Family Codes must retain `{family_codes}`."),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
    ]
    if notice:
        rows.append(hikari.impl.TextDisplayComponentBuilder(content=f"-# {notice}"))
    rows.extend([
        selector,
        _buttons(
            (f"recruit_question_preview:{sid}", "Preview", hikari.ButtonStyle.SECONDARY, False),
            (f"recruit_question_save:{sid}", "Save changes", hikari.ButtonStyle.SUCCESS, not _dirty(state)),
        ),
        _buttons(
            (f"recruit_question_footer:{sid}", "Upload footer", hikari.ButtonStyle.SECONDARY, native_footer is None),
            (f"recruit_question_restore_footer:{sid}", "Restore artwork", hikari.ButtonStyle.SECONDARY, native_footer is None or template["footer_url"] == native_footer),
            (f"recruit_question_accent:{sid}", "Edit accent", hikari.ButtonStyle.SECONDARY, False),
        ),
        _buttons(
            (f"recruit_question_reset:{sid}", "Reset defaults", hikari.ButtonStyle.DANGER, False),
        ),
        hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL),
        _buttons(
            (f"recruit_question_leave_variants:{sid}", "Back to messages", hikari.ButtonStyle.SECONDARY, False),
            (f"{'recruit_question_leave' if _dirty(state) else 'manage_home'}:{sid if _dirty(state) else state['manage_token']}", "Management Home", hikari.ButtonStyle.SECONDARY, False),
        ),
    ])
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLD_ACCENT, components=rows)]


def _leave_review(state: dict, *, management: bool) -> list:
    sid = state["_id"]
    destination = "Management Home" if management else "message list"
    leave_id = f"manage_home:{state['manage_token']}" if management else f"recruit_question_back:{sid}"
    return [hikari.impl.ContainerComponentBuilder(accent_color=GOLD_ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content=f"## Return to {destination}?"),
        hikari.impl.TextDisplayComponentBuilder(content="Unsaved changes in this draft will not be restored. Save them first if you want future recruitment messages to use them."),
        _buttons(
            (f"recruit_question_back_editor:{sid}", "Keep editing", hikari.ButtonStyle.PRIMARY, False),
            (leave_id, "Leave without saving", hikari.ButtonStyle.SECONDARY, False),
        ),
    ])]


async def open_dashboard(ctx: Any, mongo: MongoClient, *, manage_token: str, deferred: bool = False) -> None:
    if not allowed(ctx):
        await ctx.respond("Manage Server permission is required to manage recruitment questions.", ephemeral=True)
        return
    if not deferred and not getattr(ctx.interaction, "custom_id", None):
        await ctx.defer(ephemeral=True)
    user_id, guild_id = _identity(ctx)
    if user_id is None or guild_id is None:
        await ctx.interaction.edit_initial_response(content="Open `/manage` inside a server.")
        return
    state = await _new_state(mongo, user_id=user_id, guild_id=guild_id, manage_token=manage_token, view="home")
    await ctx.interaction.edit_initial_response(components=_home(state), **NO_MENTIONS)


async def _ack_modal(ctx: Any) -> None:
    if getattr(ctx.interaction, "message", None) is not None:
        await ctx.interaction.create_initial_response(hikari.ResponseType.DEFERRED_MESSAGE_UPDATE)
    else:
        await ctx.defer(ephemeral=True)


async def _modal_edit(ctx: Any, components: list) -> None:
    await ctx.interaction.edit_initial_response(components=components, **NO_MENTIONS)


def _modal_value(ctx: Any, field: str) -> str:
    return next(
        (str(item.value or "") for row in getattr(ctx.interaction, "components", ()) for item in row
         if getattr(item, "custom_id", None) == field),
        "",
    )


def _selected(ctx: Any, options: set[str]) -> str | None:
    values = getattr(ctx.interaction, "values", ()) or ()
    return values[0] if len(values) == 1 and values[0] in options else None


@register_action("recruit_question_variant", preload_state=False)
@lightbulb.di.with_di
async def variant(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="home")
    if problem:
        return _error(problem)
    key = _selected(ctx, set(content.VARIANTS))
    if key is None:
        return _home(state, "Choose one supported recruitment message.")
    try:
        template = await content.load_template(mongo, state["guild_id"], key)
    except ValueError as exc:
        return _home(state, str(exc))
    draft = await _next(
        mongo, state, view="editor", variant=key,
        template=template, saved_template=copy.deepcopy(template),
    )
    return _editor(draft)


@register_action("recruit_question_block", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def block(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    key = _selected(ctx, {str(index) for index in range(len(state["template"]["sections"]))})
    if key is None:
        await _ack_modal(ctx)
        await _modal_edit(ctx, _editor(state, "Choose one editable text block."))
        return
    text = state["template"]["sections"][int(key)]
    limit = 2000
    await ctx.respond_with_modal(
        title=content.BLOCK_LABELS[state["variant"]][int(key)][:45],
        custom_id=f"recruit_question_submit:{action_id}|{key}",
        components=[hikari.impl.ModalActionRowBuilder().add_text_input(
            "text", "Text", value=text, required=True, min_length=1,
            max_length=limit, style=hikari.TextInputStyle.PARAGRAPH,
        )],
    )


@register_action("recruit_question_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def submit(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _ack_modal(ctx)
    sid, separator, key = action_id.partition("|")
    if not separator or not sid:
        await _modal_edit(ctx, _error("This text form is out of date."))
        return
    state, problem = await _state(ctx, mongo, sid, view="editor")
    if problem:
        await _modal_edit(ctx, _error(problem))
        return
    options = {str(index) for index in range(len(state["template"]["sections"]))}
    value = _modal_value(ctx, "text")
    if key not in options or not value.strip():
        await _modal_edit(ctx, _editor(state, "Choose one supported block and enter text."))
        return
    template = copy.deepcopy(state["template"])
    template["sections"][int(key)] = value
    try:
        content.validate_template(state["variant"], template)
    except ValueError as exc:
        await _modal_edit(ctx, _editor(state, str(exc)))
        return
    draft = await _next(mongo, state, template=template)
    await _modal_edit(ctx, _editor(draft, "Draft updated. Save changes before using this message."))


@register_action("recruit_question_preview", preload_state=False, no_return=True)
@lightbulb.di.with_di
async def preview(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        await _modal_edit(ctx, _error(problem))
        return
    try:
        components = content.preview_template(state["template"])
    except ValueError as exc:
        await _modal_edit(ctx, _editor(state, str(exc)))
        return
    nav = hikari.impl.ContainerComponentBuilder(accent_color=GOLD_ACCENT, components=[
        _buttons((f"recruit_question_back_editor:{action_id}", "Back to editor", hikari.ButtonStyle.SECONDARY, False)),
    ])
    await _modal_edit(ctx, [*components, nav])


@register_action("recruit_question_back_editor", preload_state=False)
@lightbulb.di.with_di
async def back_editor(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    return _error(problem) if problem else _editor(state)


@register_action("recruit_question_back", preload_state=False)
@lightbulb.di.with_di
async def back(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        return _error(problem)
    return _home(await _home_state(mongo, state))


@register_action("recruit_question_leave_variants", preload_state=False)
@lightbulb.di.with_di
async def leave_variants(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        return _error(problem)
    if _dirty(state):
        return _leave_review(state, management=False)
    return _home(await _home_state(mongo, state))


@register_action("recruit_question_leave", preload_state=False)
@lightbulb.di.with_di
async def leave(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        return _error(problem)
    return _leave_review(state, management=True)


@register_action("recruit_question_save", preload_state=False)
@lightbulb.di.with_di
async def save(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        return _error(problem)
    if not _dirty(state):
        return _editor(state, "This template is already saved.")
    try:
        saved = await content.save_template(
            mongo, state["guild_id"], state["variant"], state["template"],
            state["template"]["revision"], state["user_id"],
        )
    except content.TemplateConflict:
        return _editor(state, "This template changed elsewhere. Reopen it before saving.")
    except ValueError as exc:
        return _editor(state, str(exc))
    draft = await _next(mongo, state, template=saved, saved_template=copy.deepcopy(saved))
    return _editor(draft, "Saved. Future recruitment questions use this template.")


@register_action("recruit_question_reset", preload_state=False)
@lightbulb.di.with_di
async def reset(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        return _error(problem)
    return [hikari.impl.ContainerComponentBuilder(accent_color=RED_ACCENT, components=[
        hikari.impl.TextDisplayComponentBuilder(content="## Reset this recruitment message?"),
        hikari.impl.TextDisplayComponentBuilder(content="This restores the original text, accent, and artwork for future posts. Any unsaved edits in this draft will be discarded."),
        _buttons(
            (f"recruit_question_reset_confirm:{action_id}", "Reset defaults", hikari.ButtonStyle.DANGER, False),
            (f"recruit_question_back_editor:{action_id}", "Keep editing", hikari.ButtonStyle.SECONDARY, False),
        ),
    ])]


@register_action("recruit_question_reset_confirm", preload_state=False)
@lightbulb.di.with_di
async def reset_confirm(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        return _error(problem)
    try:
        saved = await content.reset_template(
            mongo, state["guild_id"], state["variant"],
            state["template"]["revision"], state["user_id"],
        )
    except content.TemplateConflict:
        return _editor(state, "This template changed elsewhere. Reopen it before resetting.")
    draft = await _next(mongo, state, template=saved, saved_template=copy.deepcopy(saved))
    return _editor(draft, "Defaults restored for future posts.")


@register_action("recruit_question_accent", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def accent(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    await ctx.respond_with_modal(
        title="Edit accent color",
        custom_id=f"recruit_question_accent_submit:{action_id}",
        components=[hikari.impl.ModalActionRowBuilder().add_text_input(
            "accent", "Hex color", value=f"{state['template']['accent']:06X}",
            required=True, min_length=6, max_length=7,
        )],
    )


@register_action("recruit_question_accent_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def accent_submit(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    await _ack_modal(ctx)
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        await _modal_edit(ctx, _error(problem))
        return
    raw = _modal_value(ctx, "accent").strip()
    if not _HEX_COLOR.fullmatch(raw):
        await _modal_edit(ctx, _editor(state, "Use a six-digit hex color, such as D4AF37."))
        return
    template = copy.deepcopy(state["template"])
    template["accent"] = int(raw.lstrip("#"), 16)
    try:
        content.validate_template(state["variant"], template)
    except ValueError as exc:
        await _modal_edit(ctx, _editor(state, str(exc)))
        return
    draft = await _next(mongo, state, template=template)
    await _modal_edit(ctx, _editor(draft, "Accent updated in this draft. Save changes before posting."))


def _modal_attachment(payload: dict | None) -> hikari.Attachment | None:
    if payload is None:
        return None
    try:
        return hikari.Attachment(
            id=hikari.Snowflake(payload["id"]),
            filename=payload["filename"],
            title=payload.get("title"),
            description=payload.get("description"),
            media_type=payload.get("content_type"),
            size=int(payload["size"]),
            url=payload["url"],
            proxy_url=payload.get("proxy_url", payload["url"]),
            height=payload.get("height"),
            width=payload.get("width"),
            is_ephemeral=payload.get("ephemeral", False),
            duration=payload.get("duration_secs"),
            waveform=payload.get("waveform"),
        )
    except (KeyError, TypeError, ValueError):
        return None


@register_action("recruit_question_footer", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def footer(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> None:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        await ctx.respond(problem, ephemeral=True)
        return
    if content.default_template(state["variant"])["footer_url"] is None:
        await ctx.respond("This recruitment message has no footer artwork.", ephemeral=True)
        return
    await ctx.respond_with_modal(
        title="Upload footer artwork",
        custom_id=f"recruit_question_footer_submit:{action_id}",
        components=[FileUploadModalComponentBuilder(
            custom_id="image", label="Footer image",
            description="PNG, JPG, GIF, or WEBP; maximum 10 MB",
        )],
    )


@register_action("recruit_question_footer_submit", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def footer_submit(
    ctx: Any,
    action_id: str,
    mongo: MongoClient = lightbulb.di.INJECTED,
    media: MediaStore = lightbulb.di.INJECTED,
    **_: Any,
) -> None:
    interaction = ctx.interaction
    payload = pop_file_upload(interaction.id, interaction.custom_id, "image")
    await _ack_modal(ctx)
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        await _modal_edit(ctx, _error(problem))
        return
    if content.default_template(state["variant"])["footer_url"] is None:
        await _modal_edit(ctx, _editor(state, "This recruitment message has no footer artwork."))
        return
    attachment = _modal_attachment(payload)
    if attachment is None or attachment.size <= 0 or attachment.size > MAX_IMAGE_BYTES:
        await _modal_edit(ctx, _editor(state, "Upload one PNG, JPG, GIF, or WEBP image under 10 MB. Your draft is unchanged."))
        return
    try:
        data = await attachment.read()
        url = await media.upload_bytes(
            data, folder=f"recruitment/questions/{state['guild_id']}", name=f"{state['variant']}-footer",
        )
    except (hikari.HTTPError, OSError, MediaStoreError) as exc:
        await _modal_edit(ctx, _editor(state, f"{exc} Your draft is unchanged."))
        return
    template = copy.deepcopy(state["template"])
    template["footer_url"] = url
    try:
        content.validate_template(state["variant"], template)
    except ValueError as exc:
        await _modal_edit(ctx, _editor(state, str(exc)))
        return
    draft = await _next(mongo, state, template=template)
    await _modal_edit(ctx, _editor(draft, "Footer uploaded to this draft. Save changes to use it in future posts."))


@register_action("recruit_question_restore_footer", preload_state=False)
@lightbulb.di.with_di
async def restore_footer(ctx: Any, action_id: str, mongo: MongoClient = lightbulb.di.INJECTED, **_: Any) -> list:
    state, problem = await _state(ctx, mongo, action_id, view="editor")
    if problem:
        return _error(problem)
    native_footer = content.default_template(state["variant"])["footer_url"]
    if native_footer is None:
        return _editor(state, "This recruitment message has no footer artwork.")
    template = copy.deepcopy(state["template"])
    template["footer_url"] = native_footer
    draft = await _next(mongo, state, template=template)
    return _editor(draft, "Original artwork restored in this draft. Save changes to use it.")
