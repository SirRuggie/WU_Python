"""Private Warrior nickname wizard; Discord transport stays in the extension."""

import asyncio
import logging
from functools import wraps
from weakref import WeakValueDictionary
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
from .timing import click, read
from utils.component_state import update_state, get_state
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


_locks = WeakValueDictionary()
_tasks = set()


def panel_lock(sid):
    lock = _locks.get(str(sid))
    if lock is None:
        lock = asyncio.Lock()
        _locks[str(sid)] = lock
    return lock


def serialized(fn):
    @wraps(fn)
    async def guarded(ctx, action_id, *args, **kwargs):
        async with panel_lock(action_id.split(":", 1)[0]):
            return await fn(ctx, action_id, *args, **kwargs)

    return guarded


async def stop():
    tasks = tuple(_tasks)
    for task in tasks:
        task.cancel()
    await asyncio.gather(*tasks, return_exceptions=True)


async def abandon(mongo, data):
    state = data.get("nickname_setup") or {}
    if state.get("nonce"):
        await update_state(
            mongo,
            {"_id": data["_id"], "nickname_setup.nonce": state["nonce"]},
            {"$unset": {"nickname_setup": ""}},
        )


async def load_names(ctx, data, mongo, coc_client, state, user_id):
    from extensions.commands.warrior import show

    try:
        choices = await read(
            "linked_accounts", name_choices(coc_client, user_id), target_id=int(user_id)
        )
    except asyncio.CancelledError:
        raise
    except Exception as error:
        log.warning(
            "warrior background lookup unavailable target_id=%s error=%s",
            user_id,
            type(error).__name__,
        )
        choices = {"accounts": [], "suggested": None, "unavailable": True}
    try:
        async with panel_lock(data["_id"]):
            current = await get_state(mongo, data["_id"])
            saved = (current or {}).get("nickname_setup") or {}
            if saved.get("nonce") != state["nonce"] or saved.get("step") != "name":
                return
            # A typed modal retains its nonce; never invalidate or overwrite it.
            updated = dict(
                saved,
                accounts=choices["accounts"],
                unavailable=choices["unavailable"],
                loading=False,
            )
            suggested = choices.get("suggested")
            if suggested and not saved.get("manual_name"):
                updated.update(
                    name=suggested["name"],
                    name_source_tag=suggested["tag"],
                    step="country",
                )
            result = await update_state(
                mongo,
                {
                    "_id": data["_id"],
                    "nickname_setup.nonce": state["nonce"],
                    "nickname_setup.step": "name",
                },
                {"$set": {"nickname_setup": updated}},
            )
            if result.matched_count:
                await show(ctx, render(data, updated))
    except Exception as error:
        log.warning(
            "warrior background update unavailable target_id=%s error=%s",
            user_id,
            type(error).__name__,
        )


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
                    content=(
                        "Checking linked accounts…"
                        if state.get("loading")
                        else "No linked player name is available. Type the in-game name."
                    )
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
    query = {"_id": data["_id"], "nickname_setup.step": {"$ne": "applying"}}
    if old_nonce is not None:
        query["nickname_setup.nonce"] = old_nonce
        query["nickname_setup.step"] = {"$in": ["name", "country", "zone", "preview"]}
    result = await update_state(mongo, query, {"$set": {"nickname_setup": state}})
    if not result.matched_count:
        raise core.SetupError("This nickname step changed. Use the current controls.")
    return state


async def begin(ctx, data, c, mongo, coc_client):
    from extensions.commands.warrior import show

    authorize(c)
    current = await read(
        "mongo.member_profile",
        MemberProfiles(mongo).get(c["member"].id),
        target_id=int(c["member"].id),
    )
    state = {
        "step": "name",
        "accounts": [],
        "unavailable": False,
        "loading": True,
        "profile_revision": int((current or {}).get("revision", 0)),
        "name": "",
        "name_source_tag": None,
    }
    state = await persist(mongo, data, state)
    await show(ctx, render(data, state))
    task = asyncio.create_task(
        load_names(ctx, data, mongo, coc_client, state, c["member"].id)
    )
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def save(ctx, data, c, mongo, state, bot):
    from extensions.commands.warrior import home, show

    authorize(c)
    value = nickname(state["name"], state["zone_id"], state["country"])
    store = MemberProfiles(mongo)
    consumed = await store.consume_preview(
        data["_id"],
        state["nonce"],
        guild_id=c["guild"].id,
        discord_id=c["member"].id,
        actor_id=ctx.user.id,
    )
    if not consumed:
        if not await store.preview_current(data["_id"], state["nonce"]):
            return
        raise core.SetupError(
            "This preview was already used. Check the member before editing again."
        )
    fields = {k: state.get(k) for k in ("zone_id", "country", "name_source_tag")}

    discord_confirmed = False

    async def change():
        nonlocal discord_confirmed
        async with asyncio.timeout(20):
            fresh = await core.context(
                bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
            )
            authorize(fresh)
            try:
                await read(
                    "rest.nickname_write",
                    bot.rest.edit_member(
                        c["guild"].id,
                        c["member"].id,
                        nickname=value,
                        reason=f"Warrior Setup by {ctx.user.id}",
                    ),
                    guild_id=int(c["guild"].id),
                    target_id=int(c["member"].id),
                )
            except (
                hikari.ForbiddenError,
                hikari.BadRequestError,
                hikari.NotFoundError,
            ) as error:
                reason = str(error.message or "Discord refused the nickname change.")
                if isinstance(error, hikari.BadRequestError) and error.errors:
                    details = []

                    def collect(fields, path=""):
                        if not isinstance(fields, dict):
                            return
                        for key, value in fields.items():
                            if key == "_errors" and isinstance(value, list):
                                for item in value:
                                    if isinstance(item, dict) and item.get("message"):
                                        details.append(f"{path}: {item['message']}")
                            elif isinstance(value, dict):
                                collect(value, f"{path}.{key}" if path else key)

                    collect(error.errors)
                    if details:
                        reason += ". " + "; ".join(details)[:900]
                if isinstance(error, hikari.ForbiddenError):
                    reason = (
                        "Missing permission, or that member is above the bot. " + reason
                    )
                if isinstance(error, hikari.NotFoundError):
                    reason = "That member is no longer available. " + reason
                raise core.SetupError(
                    reason.rstrip(" .!?")
                    + ". Nothing changed in Discord; no profile was saved."
                ) from error
            discord_confirmed = True

    try:
        await store.commit_after(
            c["member"].id,
            fields,
            change=change,
            expected_revision=state["profile_revision"],
            updated_by=ctx.user.id,
            source="warrior",
        )
    except BaseException as error:
        # Receipt storage can fail too; never replace the confirmed Discord outcome.
        current = None
        try:
            current = await store.finish_preview(
                data["_id"], state["nonce"], "needs_attention"
            )
        except Exception as receipt_error:
            log.warning(
                "Nickname receipt unavailable (%s)", type(receipt_error).__name__
            )
        if discord_confirmed and isinstance(error, Exception):
            await ctx.respond(
                "Nickname changed in Discord; profile save not confirmed. Storage did not confirm the save; check the profile before another edit.",
                ephemeral=True,
            )
            return
        if current is False and isinstance(error, core.SetupError):
            await ctx.respond(str(error), ephemeral=True)
            return
        if current is False and isinstance(error, Exception):
            log.warning(
                "Nickname result belongs to an abandoned preview (%s)",
                type(error).__name__,
            )
            return
        raise
    try:
        if not await store.finish_preview(data["_id"], state["nonce"], "saved"):
            return
        refreshed = await core.context(
            bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
        )
        if await store.preview_current(data["_id"], state["nonce"]):
            await show(
                ctx,
                await home(
                    data, refreshed, mongo, "Nickname and member time zone saved."
                ),
            )
    except Exception as error:
        from extensions.commands.warrior import panel, back

        log.warning(
            "Nickname saved but setup summary failed (%s)", type(error).__name__
        )
        try:
            current = await store.preview_current(data["_id"], state["nonce"])
        except Exception:
            await ctx.respond(
                "Nickname and member profile saved. The setup summary could not reload; return to refresh it.",
                ephemeral=True,
            )
            return
        if not current:
            return
        await show(
            ctx,
            panel(
                "Nickname saved",
                Text(
                    content="Nickname and member profile saved. The setup summary could not reload; return to refresh it."
                ),
                *back(data["_id"]),
            ),
        )


@register_action("warrior_nick", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
@serialized
@click
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
        from utils.component_state import get_state

        data = await get_state(mongo, sid)
        state = (data or {}).get("nickname_setup") or {}
        if (
            not data
            or data.get("type") != "warrior_setup"
            or int(data.get("guild_id", 0)) != int(ctx.guild_id or 0)
            or int(data.get("recruiter_id", 0)) != int(ctx.user.id)
            or state.get("nonce") != nonce
            or state.get("step") not in ("name", "country", "preview")
        ):
            await ctx.respond(
                "This private nickname form expired. Use the current controls.",
                ephemeral=True,
            )
            return
        if not country and state.get("step") == "name":
            changed = await update_state(
                mongo,
                {
                    "_id": sid,
                    "nickname_setup.nonce": nonce,
                    "nickname_setup.step": "name",
                },
                {"$set": {"nickname_setup.manual_name": True}},
            )
            if not changed.matched_count:
                await ctx.respond("Use the current nickname controls.", ephemeral=True)
                return
        await ctx.respond_with_modal(
            title="Country code" if country else "In-game name",
            custom_id=f"warrior_nick_form:{sid}:{nonce}:"
            + ("country" if country else "name"),
            components=[
                ModalRow().add_text_input(
                    "value",
                    "Two-letter country code" if country else "In-game name",
                    max_length=2 if country else 32,
                    value=(
                        state.get("country", "") if country else state.get("name", "")
                    )[: 2 if country else 32]
                    or hikari.UNDEFINED,
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
        else "The operation was not confirmed. Check the current nickname and member profile before making a new edit."
    )
    await show(
        ctx, panel("Nickname needs attention", Text(content=message[:1000]), *back(sid))
    )


@register_action(
    "warrior_nick_form", is_modal=True, no_return=True, preload_state=False
)
@lightbulb.di.with_di
@serialized
@click
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
