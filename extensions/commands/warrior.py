"""Warrior Setup, the supported replacement for the retired recruit dashboard."""

import asyncio
import logging
from uuid import uuid4
import hikari
import lightbulb
from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MessageActionRowBuilder as Row,
    SectionComponentBuilder as Section,
    ThumbnailComponentBuilder as Thumbnail,
    ModalActionRowBuilder as ModalRow,
)
from extensions.components import register_action
from extensions.warrior import core, walkthrough
from utils.mongo import MongoClient
from utils.emoji import emojis
from utils.component_state import insert_state, update_state
from utils.constants import GOLDENROD_ACCENT, RED_ACCENT, GREEN_ACCENT

loader = lightbulb.Loader()
warrior = lightbulb.Group("warrior", "Warrior setup and onboarding commands")
loader.command(warrior)
log = logging.getLogger(__name__)
ICONS = {
    "back": 1536796427198668911,
    "home": 1536924506147524730,
    "next": 1536793616004022403,
    "prev": 1536793616863862784,
    "refresh": 1536798918858514502,
    "advanced": 1537238367857676310,
    "edit": 1537264251603779764,
    "yes": 1397096942907166831,
    "no": 1397096986506825778,
}


def button(
    row, sid, verb, label, icon=None, style=hikari.ButtonStyle.SECONDARY, disabled=False
):
    return row.add_interactive_button(
        style,
        f"warrior:{sid}:{verb}",
        label=label,
        emoji=hikari.Snowflake(ICONS[icon]) if icon else hikari.UNDEFINED,
        is_disabled=disabled,
    )


def panel(title, *items, color=GOLDENROD_ACCENT):
    return [
        Container(accent_color=color, components=[Text(content=f"## {title}"), *items])
    ]


def back(sid):
    return Separator(), button(Row(), sid, "home", "Return to Warrior Setup", "back")


async def show(ctx, components):
    await ctx.interaction.edit_initial_response(
        components=components,
        user_mentions=False,
        role_mentions=False,
        mentions_everyone=False,
    )


async def home(data, c, mongo, note=""):
    sid = data["_id"]
    cfg = await core.settings(mongo, c["guild"].id)
    clans = await core.clans(mongo, c)
    member = c["member"]
    held = set(member.role_ids)
    th = [k for k, v in cfg["townhalls"].items() if int(v) in held]
    names = [
        f"{r.get('emoji') or ''} {r['name']}".strip()
        for r in clans
        if int(r["role_id"]) in held
    ]
    role_names = {int(role.id): role.name for role in c["roles"]}
    standard = {
        "family": ("👨‍👩‍👧‍👦", "Family"),
        "recruit": ("🆕", "New Recruit"),
        "strike_accepted": ("✅", "Strike System Accepted"),
        "visitor": ("👋", "Visitor"),
    }
    member_roles = [
        f"{icon} {role_names.get(int(cfg['roles'][key]), label)}"
        for key, (icon, label) in standard.items()
        if int(cfg["roles"][key]) in held
    ]
    town_halls = [f"{getattr(emojis, 'TH' + str(level))} TH{level}" for level in th]

    def listing(values, empty, budget=450):
        shown = []
        for value in values:
            if len(", ".join(shown + [value])) > budget:
                return ", ".join(shown) + f" · +{len(values) - len(shown)} more"
            shown.append(value)
        return ", ".join(shown) or empty

    needed = [
        key
        for key in ("family", "recruit", "strike_accepted")
        if int(cfg["roles"][key]) not in held
    ]
    run = await mongo.warrior_walkthroughs.find_one(
        {"_id": walkthrough.run_id(c["guild"].id, member.id)}
    )
    if run and run.get("cleanup_done") and "recruit" in needed:
        needed.remove("recruit")
    tour = (
        "Not started"
        if not run
        else f'{run["state"].title()} · {run.get("next_step",0)}/7 messages delivered'
    )
    details = f"<@{member.id}>\n" f'**Nickname:** {member.nickname or "Not set"}'
    readiness = (
        "✅ Required member roles assigned."
        if not needed
        else "⚠️ Missing: " + ", ".join(standard[key][1] for key in needed)
    )
    items = [
        Text(
            content=(
                "Set up this warrior’s nickname and roles, then start their server walkthrough "
                "from their open ticket. Review the current roles below before making changes."
            )
        ),
        Separator(),
        Text(
            content=(
                "### 📋 Information to Have Ready\n"
                "• **In-Game Name (IGN):** The recruit’s in-game name.\n"
                "• **Time Zone and Country:** Used in their server nickname.\n"
                "• **Accounts and Town Halls:** Number of accounts and each Town Hall level.\n"
                "• **Clan:** The clan they are joining."
            )
        ),
        Separator(),
        Section(
            components=[Text(content=details)],
            accessory=Thumbnail(media=str(member.display_avatar_url)),
        ),
        Text(
            content=(
                "### 📋 Current Roles\n"
                f"**Town Hall Roles:** {listing(town_halls, 'Not set', 800)}\n\n"
                f"**Clan Roles:** {listing(names, 'Not assigned')}\n\n"
                f"**Member Roles:** {listing(member_roles, 'Not assigned')}"
            )
        ),
        Separator(),
        Text(content=f"### Setup Progress\n{readiness}\n**Walkthrough:** {tour}"),
        Separator(),
    ]
    if note:
        items.append(Text(content=note[:450]))
    if run and run.get("error"):
        items.append(Text(content="**Needs attention:** " + run["error"][:200]))
    items += [
        button(
            button(Row(), sid, "nick", "1 · Set Server Nickname", "edit"),
            sid,
            "roles",
            "2 · Manage Member Roles",
        ),
        button(
            button(Row(), sid, "th", "3 · Set Town Hall Roles"),
            sid,
            "clans:0",
            "4 · Assign Clan Roles",
        ),
        button(
            Row(),
            sid,
            "tour",
            "5 · Server Walkthrough",
            style=hikari.ButtonStyle.SUCCESS,
        ),
        Separator(),
        button(
            button(Row(), sid, "home", "Refresh", "refresh"),
            sid,
            "advanced",
            "Advanced",
            "advanced",
        ),
    ]
    return panel("Warrior Setup", *items)


@warrior.register()
class WarriorSetup(
    lightbulb.SlashCommand,
    name="setup",
    description="Set up a warrior’s nickname, roles, clans and server walkthrough",
):
    user = lightbulb.user("discord-user", "Member to set up")

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
        self,
        ctx: lightbulb.Context,
        mongo: MongoClient = lightbulb.di.INJECTED,
        bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    ):
        await ctx.defer(ephemeral=True)
        try:
            if not ctx.guild_id:
                raise core.SetupError("Run /warrior setup in the server.")
            c = await core.context(
                bot, mongo, int(ctx.guild_id), int(ctx.user.id), int(self.user.id)
            )
            data = {
                "_id": str(ctx.interaction.id),
                "type": "warrior_setup",
                "guild_id": int(ctx.guild_id),
                "user_id": int(self.user.id),
                "recruiter_id": int(ctx.user.id),
            }
            await insert_state(mongo, data)
            await ctx.respond(
                components=await home(data, c, mongo),
                ephemeral=True,
                user_mentions=False,
                role_mentions=False,
            )
        except (core.SetupError, hikari.HTTPError) as error:
            await ctx.respond(str(error)[:1500], ephemeral=True)


def role_menu(sid, operation):
    row = Row()
    row.add_select_menu(
        hikari.ComponentType.ROLE_SELECT_MENU,
        f"warrior:{sid}:role_{operation}",
        placeholder=f"Select roles to {operation}",
        min_values=1,
        max_values=25,
    )
    return panel(
        "Member Roles",
        Text(
            content="Only roles you and the bot are permitted to manage can be changed."
        ),
        row,
        *back(sid),
    )


def th_menu(data, c, cfg):
    sid = data["_id"]
    row = Row()
    menu = row.add_text_menu(
        f"warrior:{sid}:set_th",
        placeholder="Select all Town Hall roles this member should have",
        min_values=1,
        max_values=len(cfg["townhalls"]),
    )
    for level, rid in cfg["townhalls"].items():
        menu.add_option(
            f"TH{level}", str(rid), is_default=int(rid) in c["member"].role_ids
        )
    return panel(
        "Town Hall Roles",
        Text(
            content="Your selection replaces only the configured Town Hall roles. Other roles stay in place."
        ),
        row,
        button(Row(), sid, "confirm:clear_th", "Clear Town Hall Roles"),
        *back(sid),
    )


async def clan_menu(data, c, mongo, page=0, tour=False):
    clans = await core.clans(mongo, c)
    sid = data["_id"]
    if tour:
        clans = [r for r in clans if int(r["role_id"]) in c["member"].role_ids]
    pages = max(1, (len(clans) + 24) // 25)
    page = max(0, min(page, pages - 1))
    items = []
    if clans:
        row = Row()
        menu = row.add_text_menu(
            f"warrior:{sid}:" + ("tour_choose" if tour else "clan_add"),
            placeholder=(
                "Choose one clan for the walkthrough"
                if tour
                else "Select clan roles to add"
            ),
            min_values=1,
            max_values=1 if tour else min(25, len(clans[page * 25 : page * 25 + 25])),
        )
        for clan in clans[page * 25 : page * 25 + 25]:
            menu.add_option(
                str(clan["name"])[:100], str(clan["tag"]), description=str(clan["tag"])
            )
        items.append(row)
    else:
        items.append(
            Text(
                content=(
                    "Assign a clan role first."
                    if tour
                    else "No clan roles are configured in this server."
                )
            )
        )
    if pages > 1:
        prefix = "tourpage" if tour else "clans"
        items.append(
            button(
                button(
                    Row(),
                    sid,
                    f"{prefix}:{page-1}",
                    "Previous",
                    "prev",
                    disabled=page == 0,
                ),
                sid,
                f"{prefix}:{page+1}",
                "Next",
                "next",
                disabled=page == pages - 1,
            )
        )
        items.append(Text(content=f"Page {page+1}/{pages}"))
    return panel("Server Walkthrough" if tour else "Clan Roles", *items, *back(sid))


def confirm(data, action, text):
    return panel(
        "Confirm change",
        Text(content=text),
        button(
            button(
                Row(),
                data["_id"],
                f"apply:{action}",
                "Confirm",
                "yes",
                style=hikari.ButtonStyle.DANGER,
            ),
            data["_id"],
            "home",
            "Cancel",
            "no",
        ),
    )


async def advanced(data, c, mongo):
    sid = data["_id"]
    rows = [
        Text(content="Bulk actions require confirmation."),
        button(
            button(Row(), sid, "confirm:all_clans", "Add All Clan Roles"),
            sid,
            "confirm:clear_clans",
            "Remove All Clan Roles",
        ),
        button(Row(), sid, "confirm:restart", "Restart Completed Walkthrough"),
    ]
    return panel("Advanced Setup", *rows, *back(sid))


async def settings_page(data, c, mongo, page=0):
    if not c["actor_permissions"] & hikari.Permissions.ADMINISTRATOR:
        raise core.SetupError("Administrator permission is required for settings.")
    cfg = await core.settings(mongo, c["guild"].id)
    keys = [(group, key) for group in cfg for key in cfg[group]]
    page = max(0, min(page, (len(keys) - 1) // 25))
    row = Row()
    menu = row.add_text_menu(
        f'warrior:{data["_id"]}:setting',
        placeholder="Choose a role or channel to configure",
    )
    for group, key in keys[page * 25 : page * 25 + 25]:
        menu.add_option(
            f'{group.title()} · {key.replace("_"," ")}',
            f"{group}:{key}",
            description=str(cfg[group][key]),
        )
    items = [
        Text(
            content="Settings apply only to /warrior in this server. Clan announcement/chat destinations continue to use the existing clan configuration."
        ),
        row,
    ]
    if len(keys) > 25:
        items.append(
            button(
                button(
                    Row(),
                    data["_id"],
                    "settings:0",
                    "Previous",
                    "prev",
                    disabled=page == 0,
                ),
                data["_id"],
                "settings:1",
                "Next",
                "next",
                disabled=page == 1,
            )
        )
    return panel("Warrior Server Settings", *items, *back(data["_id"]))


def modal_value(ctx, name):
    from extensions.commands.tickets.console import _modal_value

    return _modal_value(ctx, name).strip()


@register_action("warrior", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def action(
    ctx,
    action_id,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs,
):
    sid, _, verb = action_id.partition(":")
    # Modals acknowledge immediately; all authorization and bounds are checked
    # again on submission before touching a member or configuration.
    if verb == "nick":
        await ctx.respond_with_modal(
            title="Warrior nickname",
            custom_id=f"warrior_form:{sid}:nick",
            components=[
                ModalRow().add_text_input(
                    "ign", "In-game name", max_length=25, required=True
                ),
                ModalRow().add_text_input(
                    "zone",
                    "Time zone (e.g. EST or UTC+5)",
                    max_length=10,
                    required=True,
                ),
                ModalRow().add_text_input(
                    "country",
                    "Country code or flag (e.g. US)",
                    max_length=4,
                    required=True,
                ),
            ],
        )
        return
    if verb == "setting":
        selected = ctx.interaction.values[0]
        await ctx.respond_with_modal(
            title="Warrior server setting",
            custom_id=f"warrior_form:{sid}:setting:{selected}",
            components=[
                ModalRow().add_text_input(
                    "id", "Role or channel ID", required=True, max_length=20
                )
            ],
        )
        return
    await ctx.defer(edit=True)
    try:
        data, c = await core.session(ctx, bot, mongo, sid)
        cfg = await core.settings(mongo, c["guild"].id)
        if verb == "home":
            output = await home(data, c, mongo)
        elif verb == "roles":
            output = panel(
                "Member Roles",
                Text(
                    content="Quick Set-up adds Family, New Recruit and Strike System Accepted, then removes Visitor only if those additions succeed."
                ),
                button(
                    button(Row(), sid, "add_roles", "Add Roles"),
                    sid,
                    "remove_roles",
                    "Remove Roles",
                ),
                button(Row(), sid, "quick", "Quick Set-up"),
                *back(sid),
            )
        elif verb in ("add_roles", "remove_roles"):
            output = role_menu(sid, "add" if verb == "add_roles" else "remove")
        elif verb in ("role_add", "role_remove"):
            selected = [int(x) for x in ctx.interaction.values]
            result = await core.change_roles(
                bot,
                mongo,
                c,
                **({"add": selected} if verb == "role_add" else {"remove": selected}),
            )
            c = await core.context(
                bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
            )
            output = await home(data, c, mongo, core.result_text(result))
        elif verb == "quick":
            result = await core.change_roles(
                bot,
                mongo,
                c,
                add=[cfg["roles"][x] for x in ("family", "recruit", "strike_accepted")],
            )
            if not result["failed"]:
                removed = await core.change_roles(
                    bot, mongo, c, remove=[cfg["roles"]["visitor"]]
                )
                for key in result:
                    result[key] += removed[key]
            c = await core.context(
                bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
            )
            output = await home(data, c, mongo, core.result_text(result))
        elif verb == "th":
            output = th_menu(data, c, cfg)
        elif verb == "set_th":
            selected = {int(x) for x in ctx.interaction.values}
            allowed = set(map(int, cfg["townhalls"].values()))
            if not selected.issubset(allowed):
                raise core.SetupError(
                    "Town Hall settings changed. Refresh and select again."
                )
            # Add first. Do not strip working roles if replacements cannot be added.
            result = await core.change_roles(bot, mongo, c, add=selected)
            if not result["failed"]:
                removed = await core.change_roles(
                    bot, mongo, c, remove=allowed - selected
                )
                for key in result:
                    result[key] += removed[key]
            c = await core.context(
                bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
            )
            output = await home(data, c, mongo, core.result_text(result))
        elif verb.startswith("clans:"):
            output = await clan_menu(data, c, mongo, int(verb.split(":")[1]))
        elif verb == "clan_add":
            available = await core.clans(mongo, c)
            selected = set(ctx.interaction.values)
            if not selected.issubset({r["tag"] for r in available}):
                raise core.SetupError(
                    "Clan settings changed. Refresh and select again."
                )
            result = await core.change_roles(
                bot,
                mongo,
                c,
                add=[r["role_id"] for r in available if r["tag"] in selected],
            )
            c = await core.context(
                bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
            )
            output = await home(data, c, mongo, core.result_text(result))
        elif verb == "advanced":
            output = await advanced(data, c, mongo)
        elif verb.startswith("settings"):
            output = await settings_page(
                data, c, mongo, int(verb.split(":")[1]) if ":" in verb else 0
            )
        elif verb.startswith("confirm:"):
            operation = verb.split(":")[1]
            descriptions = {
                "all_clans": "Add every configured clan role to this member?",
                "clear_clans": "Remove every configured clan role from this member?",
                "clear_th": "Remove every configured Town Hall role from this member?",
                "restart": "Restart this member’s completed walkthrough? This will send a new welcome and repeat the tour after confirmation.",
            }
            if operation not in descriptions:
                raise core.SetupError("Unknown action.")
            token = uuid4().hex
            await update_state(
                mongo,
                sid,
                {"$set": {"confirmation": {"action": operation, "token": token}}},
            )
            output = confirm(data, operation + ":" + token, descriptions[operation])
        elif verb.startswith("apply:"):
            _, operation, token = verb.split(":")
            consumed = await mongo.component_state.find_one_and_update(
                {
                    "_id": sid,
                    "confirmation.action": operation,
                    "confirmation.token": token,
                },
                {"$unset": {"confirmation": ""}},
            )
            if not consumed:
                raise core.SetupError(
                    "This confirmation was already used or is out of date."
                )
            if operation == "restart":
                key = walkthrough.run_id(c["guild"].id, c["member"].id)
                old = await mongo.warrior_walkthroughs.find_one(
                    {"_id": key, "state": "complete"}
                )
                if not old:
                    raise core.SetupError(
                        "Only a completed walkthrough can be restarted; use Retry for interrupted steps."
                    )
                archive = dict(
                    old,
                    _id=key + ":" + old["token"],
                    kind="warrior_walkthrough_history",
                )
                await mongo.warrior_history.replace_one(
                    {"_id": archive["_id"]}, archive, upsert=True
                )
                await mongo.warrior_walkthroughs.delete_one(
                    {"_id": key, "token": old["token"], "state": "complete"}
                )
                output = await clan_menu(data, c, mongo, tour=True)
            else:
                roles = (
                    list(cfg["townhalls"].values())
                    if operation == "clear_th"
                    else [r["role_id"] for r in await core.clans(mongo, c)]
                )
                result = await core.change_roles(
                    bot,
                    mongo,
                    c,
                    **(
                        {"add": roles}
                        if operation == "all_clans"
                        else {"remove": roles}
                    ),
                )
                c = await core.context(
                    bot, mongo, c["guild"].id, ctx.user.id, c["member"].id
                )
                output = await home(data, c, mongo, core.result_text(result))
        elif verb == "tour" or verb.startswith("tourpage:"):
            run = await mongo.warrior_walkthroughs.find_one(
                {"_id": walkthrough.run_id(c["guild"].id, c["member"].id)}
            )
            if run:
                items = [
                    Text(
                        content=f'**{run["state"].title()}** · {run.get("next_step",0)}/7 messages delivered.\n'
                        + (run.get("error") or "Completed messages will not be resent.")
                    )
                ]
                if run["state"] == "paused":
                    items.append(
                        button(Row(), sid, "retry", "Retry unfinished steps", "refresh")
                    )
                items.append(
                    Row().add_link_button(
                        f'https://discord.com/channels/{run["guild_id"]}/{run["ticket_channel"]}',
                        label="Open Recruit Ticket",
                    )
                )
                output = panel("Walkthrough Progress", *items, *back(sid))
            else:
                await core.open_ticket(mongo, c["guild"].id, c["member"].id)
                output = await clan_menu(
                    data,
                    c,
                    mongo,
                    int(verb.split(":")[1]) if ":" in verb else 0,
                    tour=True,
                )
        elif verb == "tour_choose":
            clan = next(
                (
                    r
                    for r in await core.clans(mongo, c)
                    if r["tag"] == ctx.interaction.values[0]
                ),
                None,
            )
            if not clan:
                raise core.SetupError("Clan no longer available.")
            run = await walkthrough.prepare(bot, mongo, c, clan, cfg)
            output = panel(
                "Walkthrough queued",
                Text(
                    content=f'The welcome will be posted in <#{run["ticket_channel"]}>. A recruiter can press Begin Walkthrough there.'
                ),
                *back(sid),
            )
        elif verb == "retry":
            existing_run = await mongo.warrior_walkthroughs.find_one({
                "_id": walkthrough.run_id(c["guild"].id, c["member"].id),
                "state": "paused",
            })
            if not existing_run or not existing_run.get("ticket_id"):
                raise core.SetupError("There is no paused walkthrough to retry.")
            ticket = await core.open_ticket(
                mongo, c["guild"].id, c["member"].id,
                ticket_id=existing_run["ticket_id"],
            )
            await mongo.warrior_walkthroughs.update_one(
                {
                    "_id": walkthrough.run_id(c["guild"].id, c["member"].id),
                    "state": "paused",
                    "ticket_id": ticket["_id"],
                },
                {
                    "$set": {
                        "state": "running",
                        "actor_id": int(ctx.user.id),
                        "due_at": core.now(),
                        "error": None,
                    }
                },
            )
            output = await home(
                data,
                c,
                mongo,
                "Retry requested. Completed messages will not be repeated.",
            )
        else:
            raise core.SetupError(
                "This action is no longer available. Refresh the dashboard."
            )
        await show(ctx, output)
    except Exception as error:
        log.exception("warrior action error")
        log.warning(
            "warrior action failed action=%s error=%s", verb, type(error).__name__
        )
        await show(
            ctx,
            panel(
                "Set-up needs attention",
                Text(
                    content=(
                        str(error)[:1500]
                        if isinstance(error, (core.SetupError, ValueError))
                        else "The operation could not finish. Refresh to check which changes succeeded, then retry."
                    )
                ),
                *back(sid),
                color=RED_ACCENT,
            ),
        )


@register_action("warrior_form", is_modal=True, no_return=True, preload_state=False)
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
    sid, _, verb = action_id.partition(":")
    try:
        data, c = await core.session(ctx, bot, mongo, sid)
        if verb == "nick":
            core.manageable_target(c)
            if not c["bot_permissions"] & hikari.Permissions.MANAGE_NICKNAMES:
                raise core.SetupError("The bot needs Manage Nicknames.")
            value = core.nickname(
                modal_value(ctx, "ign"),
                modal_value(ctx, "zone"),
                modal_value(ctx, "country"),
            )
            await bot.rest.edit_member(
                c["guild"].id,
                c["member"].id,
                nickname=value,
                reason=f"Warrior Setup by {ctx.user.id}",
            )
            note = "Nickname updated."
        elif verb.startswith("setting:"):
            if not c["actor_permissions"] & hikari.Permissions.ADMINISTRATOR:
                raise core.SetupError("Administrator permission is required.")
            _, group, key = verb.split(":")
            cfg = await core.settings(mongo, c["guild"].id)
            if group not in cfg or key not in cfg[group]:
                raise core.SetupError("Unknown setting.")
            value = int(modal_value(ctx, "id"))
            if group == "channels":
                channel = await bot.rest.fetch_channel(value)
                if (
                    channel.guild_id != c["guild"].id
                    or channel.type != hikari.ChannelType.GUILD_TEXT
                ):
                    raise core.SetupError("Choose a text channel in this server.")
            else:
                role = next((r for r in c["roles"] if r.id == value), None)
                if not core.role_allowed(c, role):
                    raise core.SetupError(
                        "Choose an unmanaged role below the bot’s highest role in this server."
                    )
            if group != "channels" and any(
                int(rid) == value
                for g in ("roles", "townhalls")
                for k, rid in cfg[g].items()
                if (g, k) != (group, key)
            ):
                raise core.SetupError(
                    "This role is already assigned to another Warrior setting."
                )
            await mongo.warrior_settings.update_one(
                {"_id": f'warrior_settings:{c["guild"].id}'},
                {
                    "$set": {
                        f"{group}.{key}": value,
                        "schema_version": core.SCHEMA_VERSION,
                        "guild_id": int(c["guild"].id),
                        "updated_by": int(ctx.user.id),
                        "updated_at": core.now(),
                    }
                },
                upsert=True,
            )
            note = "Server setting saved. Existing walkthroughs keep their original destinations."
        else:
            raise core.SetupError("Unknown form.")
        c = await core.context(bot, mongo, c["guild"].id, ctx.user.id, c["member"].id)
        await show(ctx, await home(data, c, mongo, note))
    except Exception as error:
        log.exception("warrior form error")
        await show(
            ctx,
            panel(
                "Set-up needs attention",
                Text(
                    content=(
                        str(error)[:1500]
                        if isinstance(error, (core.SetupError, ValueError))
                        else "The operation could not finish. Refresh to check which changes succeeded, then retry."
                    )
                ),
                *back(sid),
                color=RED_ACCENT,
            ),
        )


@register_action("warrior_begin", opens_modal=True, no_return=True, preload_state=False)
@lightbulb.di.with_di
async def begin(
    ctx,
    action_id,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
    **kwargs,
):
    await ctx.defer(ephemeral=True)
    try:
        run = await mongo.warrior_walkthroughs.find_one(
            {"_id": action_id, "kind": walkthrough.KIND}
        )
        if not run or run["guild_id"] != int(ctx.guild_id):
            raise core.SetupError("This walkthrough is no longer available.")
        if not walkthrough.has_marker(
            ctx.interaction.message, walkthrough.marker(run, 0), bot.get_me().id
        ):
            raise core.SetupError("Use the current walkthrough welcome message.")
        started = await walkthrough.begin(
            bot, mongo, run, int(ctx.user.id), int(ctx.channel_id)
        )
        await show(
            ctx,
            panel(
                "Server Walkthrough",
                Text(
                    content=(
                        "Walkthrough started."
                        if started
                        else "This walkthrough has already started. Use /warrior to check its progress."
                    )
                ),
            ),
        )
    except (core.SetupError, hikari.HTTPError) as error:
        await show(
            ctx,
            panel(
                "Cannot start walkthrough",
                Text(content=str(error)[:1500]),
                color=RED_ACCENT,
            ),
        )


@loader.listener(hikari.StartedEvent)
@lightbulb.di.with_di
async def started(
    _: hikari.StartedEvent,
    mongo: MongoClient = lightbulb.di.INJECTED,
    bot: hikari.GatewayBot = lightbulb.di.INJECTED,
):
    walkthrough.start(bot, mongo)


@loader.listener(hikari.StoppingEvent)
async def stopping(_: hikari.StoppingEvent):
    await walkthrough.stop()
