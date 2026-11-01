"""Private Warrior nickname wizard; Discord transport stays in the extension."""

import asyncio
import logging
from uuid import uuid4
import hikari
import lightbulb
from hikari.impl import (
    MessageActionRowBuilder as Row,
    TextDisplayComponentBuilder as Text,
    ModalActionRowBuilder as ModalRow,
)
from extensions.components import register_action
from extensions.warrior import core
from utils.component_state import update_state
from utils.member_profiles import MemberProfiles
from utils.member_timezones import (
    COUNTRY_CHOICES,
    ZONE_CHOICES,
    SINGLE_ZONE,
    flag,
    zone,
    nickname,
    name_choices,
)
from utils.mongo import MongoClient
from utils.constants import WARRIORS_UNITED_GUILD_ID as GUILD_ID

log = logging.getLogger(__name__)


def authorize(c):
    if int(c["guild"].id) != GUILD_ID:
        raise core.SetupError(
            "Member profiles are only available in the Warriors United server."
        )
    core.manageable_target(c)
    if not c["bot_permissions"] & hikari.Permissions.MANAGE_NICKNAMES:
        raise core.SetupError("The bot needs Manage Nicknames.")


def control(data, state, verb, label, *, primary=False):
    return Row().add_interactive_button(
        hikari.ButtonStyle.PRIMARY if primary else hikari.ButtonStyle.SECONDARY,
        f"warrior_nick:{data['_id']}:{state['nonce']}:{verb}",
        label=label,
    )


def menu(data, state, verb, placeholder):
    row = Row()
    return row, row.add_text_menu(
        f"warrior_nick:{data['_id']}:{state['nonce']}:{verb}",
        placeholder=placeholder,
        min_values=1,
        max_values=1,
    )


def render(data, state, *, page=0):
    from extensions.commands.warrior import panel, back

    step = state["step"]
    items = []
    if step == "name":
        accounts = state["accounts"]
        pages = max(1, (len(accounts) + 23) // 24)
        page = max(0, min(page, pages - 1))
        if accounts:
            row, select = menu(
                data, state, "pick_name", "Which one do you want to name it?"
            )
            for index, account in enumerate(
                accounts[page * 24 : page * 24 + 24], start=page * 24
            ):
                select.add_option(
                    f"{account['name']} · TH{account['townHallLevel']}"[:100],
                    str(index),
                    description=account["tag"],
                )
            select.add_option("Type a name", "type")
            items += [Text(content="Which one do you want to name it?"), row]
            if pages > 1:
                items += [
                    control(data, state, f"page:{max(0,page-1)}", "Previous accounts"),
                    control(
                        data, state, f"page:{min(pages-1,page+1)}", "Next accounts"
                    ),
                ]
        else:
            items += [
                Text(
                    content="No linked player name is available. Type the in-game name."
                ),
                control(data, state, "type", "Type a name"),
            ]
        if state.get("unavailable"):
            items.insert(
                0,
                Text(
                    content="Some linked accounts could not be checked. Choose a loaded account or type a name; no highest Town Hall was assumed."
                ),
            )
    elif step == "country":
        row, select = menu(data, state, "pick_country", "Choose country / region")
        for code, label in COUNTRY_CHOICES:
            select.add_option(f"{flag(code)} {label}", code)
        select.add_option("Other country code", "OTHER")
        items = [row]
    elif step == "zone":
        row, select = menu(data, state, "pick_zone", "Choose standard time zone")
        for key, offset, label in ZONE_CHOICES:
            select.add_option(f"{key.upper()} · {label}"[:100], key)
        items = [
            Text(
                content="Choose their standard time zone. GMT labels can be an hour off during daylight saving."
            ),
            row,
        ]
    elif step == "preview":
        try:
            value = nickname(state["name"], state["zone_id"], state["country"])
            # JSON-like inline content is display only; all mentions remain disabled.
            safe = value.replace("`", "ˋ").replace("@", "＠")
            items = [
                Text(content=f"Preview\n`{safe}`"),
                control(data, state, "save", "Set nickname", primary=True),
            ]
        except ValueError as error:
            items = [Text(content=str(error))]
        items += [
            Text(
                content="GMT labels use standard time; daylight saving can differ by one hour."
            ),
            control(data, state, "type", "Edit / shorten name"),
            control(data, state, "country", "Edit country / time zone"),
        ]
    else:
        items = [
            Text(
                content="This preview has already been used. Check the current nickname before starting a new edit."
            )
        ]
    return panel("Warrior nickname", *items, *back(data["_id"]))


async def persist(mongo, data, state, *, old_nonce=None):
    state = dict(state, nonce=uuid4().hex)
    query = {"_id": data["_id"]}
    if old_nonce is not None:
        query["nickname_setup.nonce"] = old_nonce
    result = await update_state(mongo, query, {"$set": {"nickname_setup": state}})
    if not result.matched_count:
        raise core.SetupError("This nickname step changed. Use the current controls.")
    return state


async def begin(ctx, data, c, mongo, coc_client):
    from extensions.commands.warrior import show

    authorize(c)
    current = await MemberProfiles(mongo).get(c["member"].id)
    choices = await name_choices(coc_client, c["member"].id)
    suggested = choices["suggested"]
    state = {
        "step": "country" if suggested else "name",
        "accounts": choices["accounts"],
        "unavailable": choices["unavailable"],
        "profile_revision": int((current or {}).get("revision", 0)),
        "name": suggested["name"] if suggested else "",
        "name_source_tag": suggested["tag"] if suggested else None,
    }
    state = await persist(mongo, data, state)
    await show(ctx, render(data, state))


async def save(ctx, data, c, mongo, state, bot):
    from extensions.commands.warrior import home, show

    authorize(c)
    value = nickname(state["name"], state["zone_id"], state["country"])
    consumed = await mongo.component_state.find_one_and_update(
        {
            "_id": data["_id"],
            "nickname_setup.nonce": state["nonce"],
            "nickname_setup.step": "preview",
        },
        {"$set": {"nickname_setup.step": "applying"}},
    )
    if not consumed:
        raise core.SetupError(
            "This preview was already used. Check the member before editing again."
        )
    fields = {k: state.get(k) for k in ("zone_id", "country", "name_source_tag")}

    async def change():
        async with asyncio.timeout(20):
            fresh = await core.context(
                bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
            )
            authorize(fresh)
            await bot.rest.edit_member(
                c["guild"].id,
                c["member"].id,
                nickname=value,
                reason=f"Warrior Setup by {ctx.user.id}",
            )

    try:
        await MemberProfiles(mongo).commit_after(
            c["member"].id,
            fields,
            change=change,
            expected_revision=state["profile_revision"],
            updated_by=ctx.user.id,
            source="warrior",
        )
    except BaseException:
        # A consumed preview never automatically retries an uncertain Discord edit.
        await update_state(
            mongo, data["_id"], {"$set": {"nickname_setup.step": "needs_attention"}}
        )
        raise
    await update_state(mongo, data["_id"], {"$set": {"nickname_setup.step": "saved"}})
    refreshed = await core.context(
        bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
    )
    await show(
        ctx, await home(data, refreshed, mongo, "Nickname and member time zone saved.")
    )


@register_action("warrior_nick", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def action(
    ctx,
    action_id,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs,
):
    sid, nonce, verb = action_id.split(":", 2)
    selected = (getattr(ctx.interaction, "values", None) or [""])[0]
    if (
        verb == "type"
        or (verb == "pick_name" and selected == "type")
        or (verb == "pick_country" and selected == "OTHER")
    ):
        country = verb == "pick_country"
        await ctx.respond_with_modal(
            title="Country code" if country else "In-game name",
            custom_id=f"warrior_nick_form:{sid}:{nonce}:"
            + ("country" if country else "name"),
            components=[
                ModalRow().add_text_input(
                    "value",
                    "Two-letter country code" if country else "In-game name",
                    max_length=2 if country else 32,
                    required=True,
                )
            ],
        )
        return
    await ctx.defer(edit=True)
    try:
        from extensions.commands.warrior import show

        data, c = await core.session(ctx, bot, mongo, sid)
        authorize(c)
        state = data.get("nickname_setup") or {}
        if state.get("nonce") != nonce:
            raise core.SetupError("Use the current nickname controls.")
        if verb == "save":
            # The gateway bot is injected; context.app is not assumed by helpers.
            await save(ctx, data, c, mongo, state, bot)
            return
        if verb.startswith("page:") and state["step"] == "name":
            await show(ctx, render(data, state, page=int(verb.split(":")[1])))
            return
        if verb == "pick_name" and state["step"] == "name":
            if not selected.isdigit() or int(selected) >= len(state["accounts"]):
                raise core.SetupError("Choose a listed account.")
            account = state["accounts"][int(selected)]
            state.update(
                name=account["name"], name_source_tag=account["tag"], step="country"
            )
        elif verb == "pick_country" and state["step"] == "country":
            if selected not in dict(COUNTRY_CHOICES):
                raise core.SetupError("Choose a listed country.")
            state.update(country=selected, zone_id=SINGLE_ZONE.get(selected))
            state["step"] = "preview" if state["zone_id"] else "zone"
        elif verb == "pick_zone" and state["step"] == "zone":
            zone(selected)
            state.update(zone_id=selected, step="preview")
        elif verb == "country" and state["step"] == "preview":
            state["step"] = "country"
        else:
            raise core.SetupError("Use the current nickname step.")
        state = await persist(mongo, data, state, old_nonce=nonce)
        await show(ctx, render(data, state))
    except Exception as error:
        await failure(ctx, sid, error)


async def failure(ctx, sid, error):
    from extensions.commands.warrior import panel, back, show

    log.warning("Warrior nickname setup failed (%s)", type(error).__name__)
    message = (
        str(error)
        if isinstance(error, (ValueError, core.SetupError))
        else "Discord did not confirm the nickname change; the profile was not saved. Check the current nickname before editing again."
    )
    await show(
        ctx, panel("Nickname needs attention", Text(content=message[:1000]), *back(sid))
    )


@register_action(
    "warrior_nick_form", is_modal=True, no_return=True, preload_state=False
)
@lightbulb.di.with_di
async def form(
    ctx,
    action_id,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs,
):
    await ctx.interaction.create_initial_response(
        hikari.ResponseType.DEFERRED_MESSAGE_UPDATE
    )
    sid, nonce, kind = action_id.split(":", 2)
    try:
        from extensions.commands.warrior import modal_value, show

        data, c = await core.session(ctx, bot, mongo, sid)
        authorize(c)
        state = data.get("nickname_setup") or {}
        if state.get("nonce") != nonce or state.get("step") not in (
            "name",
            "country",
            "preview",
        ):
            raise core.SetupError(
                "This nickname form expired. Use the current controls."
            )
        value = modal_value(ctx, "value")
        if kind == "name":
            if not value:
                raise ValueError("Type an in-game name.")
            state.update(
                name=value,
                name_source_tag=None,
                step=(
                    "preview"
                    if state.get("zone_id") and state.get("country")
                    else "country"
                ),
            )
        elif kind == "country":
            flag(value)
            country = value.upper()
            state.update(country=country, zone_id=SINGLE_ZONE.get(country))
            state["step"] = "preview" if state["zone_id"] else "zone"
        else:
            raise core.SetupError("Unknown nickname form.")
        state = await persist(mongo, data, state, old_nonce=nonce)
        await show(ctx, render(data, state))
    except Exception as error:
        await failure(ctx, sid, error)
