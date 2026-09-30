"""Manage Main/FWA staff-thread talking points without altering applicant questions."""

from copy import deepcopy
from datetime import timedelta
from uuid import uuid4
import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MessageActionRowBuilder as Row,
    ModalActionRowBuilder as ModalRow,
)
from extensions.components import register_action
from utils.component_state import insert_state, get_state
from utils.constants import GOLDENROD_ACCENT
from utils.mongo import MongoClient
from utils import ticket_staff_content as content

loader = lightbulb.Loader()
PAGE_SIZE = 5
NO_MENTIONS = dict(user_mentions=False, role_mentions=False, mentions_everyone=False)


def allowed(ctx):
    member = getattr(ctx.interaction, "member", None) or getattr(ctx, "member", None)
    return bool(
        getattr(member, "permissions", 0)
        & (hikari.Permissions.ADMINISTRATOR | hikari.Permissions.MANAGE_GUILD)
    )


async def new_state(mongo, data, **changes):
    result = deepcopy(data)
    result.update(changes, _id=uuid4().hex, type="staff_thread_editor")
    await insert_state(mongo, result, ttl=timedelta(minutes=30))
    return result


async def state(ctx, mongo, token):
    data = await get_state(mongo, token)
    if not data or data.get("type") != "staff_thread_editor":
        raise ValueError(
            "This editor expired. Reopen Recruitment Staff Thread from /manage."
        )
    if data["user_id"] != int(ctx.user.id) or data["guild_id"] != int(
        ctx.interaction.guild_id or 0
    ):
        raise ValueError("Open your own editor in this server.")
    if not allowed(ctx):
        raise ValueError("Manage Server permission is required.")
    return data


def page(data, notice=""):
    token = data["_id"]
    kind = data.get("kind")
    items = [
        Text(content="-# Management › Recruitment\n## Recruitment Staff Thread"),
        Text(
            content="Edit the separate messages posted in staff threads. Main and FWA have independent templates."
        ),
    ]
    if notice:
        items.append(Text(content=notice))
    if kind:
        items += [
            Separator(),
            Text(
                content=f"### {kind.upper()} staff thread\nChanges apply to new tickets. Existing threads keep their original messages."
            ),
        ]
        sections = list(data["template"]["sections"].items())
        last_page = (len(sections) - 1) // PAGE_SIZE
        selected_page = max(0, min(int(data.get("section_page", 0)), last_page))
        if last_page:
            items.append(
                Text(
                    content=f"Page {selected_page + 1}/{last_page + 1} · {len(sections)} messages"
                )
            )
        for key, section in sections[
            selected_page * PAGE_SIZE : (selected_page + 1) * PAGE_SIZE
        ]:
            excerpt = section["body"][:180]
            items.append(
                Text(
                    content=f"**{content.section_label(key, section)}**\n{excerpt}{'…' if len(section['body']) > 180 else ''}"
                )
            )
            items.append(
                Row().add_interactive_button(
                    hikari.ButtonStyle.SECONDARY,
                    f"stafftpl:{token}:edit:{key}",
                    label=f"Edit {content.section_label(key, section)}"[:80],
                )
            )
        if last_page:
            items.append(
                Row()
                .add_interactive_button(
                    hikari.ButtonStyle.SECONDARY,
                    f"stafftpl:{token}:previous",
                    label="Previous",
                    is_disabled=selected_page == 0,
                )
                .add_interactive_button(
                    hikari.ButtonStyle.SECONDARY,
                    f"stafftpl:{token}:next",
                    label="Next",
                    is_disabled=selected_page == last_page,
                )
            )
        items += [
            Separator(),
            Text(
                content="The private-thread notice automatically includes the correct recruiter role. Do not type a role mention into the template."
            ),
            Row()
            .add_interactive_button(
                hikari.ButtonStyle.SECONDARY,
                f"stafftpl:{token}:preview",
                label="Preview",
            )
            .add_interactive_button(
                hikari.ButtonStyle.SUCCESS,
                f"stafftpl:{token}:save",
                label="Save template",
            )
            .add_interactive_button(
                hikari.ButtonStyle.SECONDARY,
                f"stafftpl:{token}:add",
                label="Add new",
                emoji="➕",
                is_disabled=len(sections) >= content.MAX_SECTIONS,
            ),
            Row().add_interactive_button(
                hikari.ButtonStyle.SECONDARY,
                f"stafftpl:{token}:home",
                label="Return to Main / FWA",
            ),
        ]
    else:
        items.append(
            Row()
            .add_interactive_button(
                hikari.ButtonStyle.SECONDARY, f"stafftpl:{token}:main", label="Main"
            )
            .add_interactive_button(
                hikari.ButtonStyle.SECONDARY, f"stafftpl:{token}:fwa", label="FWA"
            )
        )
    items += [
        Separator(),
        Row().add_interactive_button(
            hikari.ButtonStyle.SECONDARY,
            f'manage_home:{data["manage_token"]}',
            label="Return to Management Home",
        ),
    ]
    return [Container(accent_color=GOLDENROD_ACCENT, components=items)]


async def open_dashboard(ctx, mongo, *, manage_token, deferred=False):
    if not deferred:
        await ctx.defer(ephemeral=True)
    if not allowed(ctx):
        raise ValueError("Manage Server permission is required.")
    data = await new_state(
        mongo,
        dict(
            user_id=int(ctx.user.id),
            guild_id=int(ctx.interaction.guild_id),
            manage_token=manage_token,
        ),
    )
    await ctx.interaction.edit_initial_response(components=page(data), **NO_MENTIONS)


async def error(ctx, message):
    await ctx.interaction.edit_initial_response(
        components=[
            Container(
                accent_color=GOLDENROD_ACCENT, components=[Text(content=str(message))]
            )
        ],
        **NO_MENTIONS,
    )


@register_action("stafftpl", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def action(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    token, _, verb = action_id.partition(":")
    is_edit = verb.startswith("edit:") or verb == "add"
    if not is_edit:
        await ctx.defer(edit=True)
    try:
        data = await state(ctx, mongo, token)
        if is_edit:
            if not data.get("kind"):
                raise ValueError("Choose Main or FWA first.")
            key = "new" if verb == "add" else verb.split(":", 1)[1]
            if verb == "add":
                if len(data["template"]["sections"]) >= content.MAX_SECTIONS:
                    raise ValueError(
                        f"This template already has {content.MAX_SECTIONS} messages."
                    )
                section = {"title": "", "body": ""}
            else:
                if key not in data.get("template", {}).get("sections", {}):
                    raise ValueError("Reopen the template before editing.")
                section = data["template"]["sections"][key]
            await ctx.respond_with_modal(
                title=(
                    "Add new staff question"
                    if verb == "add"
                    else content.section_label(key, section)
                )[:45],
                custom_id=f"stafftpl_form:{token}:{key}",
                components=[
                    ModalRow().add_text_input(
                        "title",
                        "Heading / title (optional)",
                        value=section["title"],
                        required=False,
                        max_length=100,
                    ),
                    ModalRow().add_text_input(
                        "body",
                        "Message body",
                        value=section["body"],
                        style=hikari.TextInputStyle.PARAGRAPH,
                        required=True,
                        max_length=1800,
                    ),
                ],
            )
            return
        notice = ""
        if verb in ("main", "fwa"):
            data = await new_state(
                mongo,
                data,
                kind=verb,
                section_page=0,
                template=await content.load(mongo, data["guild_id"], verb),
            )
        elif verb in {"previous", "next"}:
            last_page = (len(data["template"]["sections"]) - 1) // PAGE_SIZE
            page_index = max(
                0,
                min(
                    int(data.get("section_page", 0)) + (1 if verb == "next" else -1),
                    last_page,
                ),
            )
            data = await new_state(mongo, data, section_page=page_index)
        elif verb == "home":
            data = await new_state(
                mongo, {k: v for k, v in data.items() if k not in ("kind", "template")}
            )
        elif verb == "save":
            saved = await content.save(
                mongo, data["guild_id"], data["kind"], data["template"], ctx.user.id
            )
            data = await new_state(mongo, data, template=saved)
            notice = "Saved. New tickets will use these staff-thread messages."
        elif verb == "preview":
            config = await mongo.ticket_setup.find_one({"_id": "config"}) or {}
            role = int(config.get(f"{data['kind']}_thread_recruiter_role") or 0)
            await ctx.interaction.edit_initial_response(
                components=page(
                    data, "Preview below is private to you; no roles will be pinged."
                ),
                **NO_MENTIONS,
            )
            for key, text in content.messages(data["kind"], data["template"], role):
                await ctx.respond(content=text, ephemeral=True, **NO_MENTIONS)
            return
        else:
            raise ValueError("Unknown editor action. Reopen /manage.")
        await ctx.interaction.edit_initial_response(
            components=page(data, notice), **NO_MENTIONS
        )
    except ValueError as exc:
        if is_edit:
            await ctx.defer(edit=True)
        await error(ctx, exc)


@register_action("stafftpl_form", is_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def form(ctx, action_id, mongo: MongoClient = lightbulb.di.INJECTED, **_):
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    try:
        token, _, key = action_id.partition(":")
        data = await state(ctx, mongo, token)
        if not data.get("kind") or (
            key != "new" and key not in data.get("template", {}).get("sections", {})
        ):
            raise ValueError("Reopen the template before editing.")
        values = {
            item.custom_id: item.value
            for row in ctx.interaction.components
            for item in row.components
        }
        template = deepcopy(data["template"])
        adding = key == "new"
        if adding:
            key = "custom_" + uuid4().hex[:16]
        template["sections"][key] = {
            "title": values.get("title", "").strip(),
            "body": values.get("body", ""),
        }
        content.validate(data["kind"], template)
        data = await new_state(
            mongo,
            data,
            template=template,
            section_page=(
                (len(template["sections"]) - 1) // PAGE_SIZE
                if adding
                else data.get("section_page", 0)
            ),
        )
        await ctx.interaction.edit_initial_response(
            components=page(
                data, "Draft updated. Choose Save template to use these changes."
            ),
            **NO_MENTIONS,
        )
    except ValueError as exc:
        await error(ctx, exc)
