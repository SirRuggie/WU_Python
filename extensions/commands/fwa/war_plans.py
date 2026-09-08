# extensions/commands/fwa/war_plans.py
"""
FWA War Plans command for generating war strategy messages.
Handles Win, Lose, Blacklisted, and Mismatch war scenarios.
"""

import hikari
import lightbulb
import coc
from datetime import datetime
from typing import Optional, Dict, List

from extensions.commands.fwa import loader, fwa
from extensions.components import register_action
from extensions.autocomplete import fwa_clans

from utils.mongo import MongoClient
from utils.classes import Clan
from utils.constants import GREEN_ACCENT, RED_ACCENT, GOLD_ACCENT, BLUE_ACCENT
from utils.fwa_blacklist import add_blacklisted
from utils.fwa_points_parser import sanitize_tag
from .message_templates import (
    WarMessageTemplates,
    WarCopyTexts,
    validate_opponent_name,
    sanitize_opponent_name
)

from hikari.impl import (
    MessageActionRowBuilder as ActionRow,
    InteractiveButtonBuilder as Button,
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

# Configuration
FWA_WAR_PLANS_CONFIG = {
    "fwa_clan_rep_role_id": 769130325460254740,
    "max_opponent_name_length": 50,
}

BLACKLIST_UNREADABLE_NOTE = (
    "Could not read the current war, so nothing was added to the blacklist; "
    "use /fwa blacklist add."
)


async def _add_war_opponent_to_blacklist(
        coc_client: coc.Client,
        mongo: MongoClient,
        clan_tag: str,
        added_by_id,
        added_by_name: str,
        typed_opponent_name: str,
) -> str:
    """After a Blacklisted war-plan is posted, try to add the CURRENT war's
    opponent (tag/name straight from the CoC API, not the typed name).

    Only adds when the CoC opponent's name matches `typed_opponent_name` -
    otherwise a plan posted while the previous war is still running (state
    still "preparation"/"inWar" for that older opponent) would blacklist that
    previous opponent instead of the one the rep actually typed.

    Never raises - a private war log, no active war, a name mismatch, or any
    API error must not fail the war-plans command itself; it only changes the
    note appended to the ephemeral confirmation.
    """
    our_tag = sanitize_tag(clan_tag)
    try:
        war = await coc_client.get_clan_war(f"#{our_tag}")
    except Exception as e:
        print(f"[FWA War Plans] Could not read war for {our_tag}: {type(e).__name__}: {e}")
        return BLACKLIST_UNREADABLE_NOTE

    state = getattr(war, "state", None)
    if state not in ("preparation", "inWar"):
        return BLACKLIST_UNREADABLE_NOTE

    opponent = getattr(war, "opponent", None)
    opponent_tag = getattr(opponent, "tag", None)
    opponent_name = getattr(opponent, "name", None)
    if not opponent_tag or not opponent_name:
        return BLACKLIST_UNREADABLE_NOTE

    normalized_coc_name = sanitize_opponent_name(opponent_name).casefold()
    normalized_typed_name = sanitize_opponent_name(typed_opponent_name).casefold()
    if normalized_coc_name != normalized_typed_name:
        return (
            f"Nothing was added to the blacklist: the current war opponent "
            f"is \"{opponent_name}\", but \"{typed_opponent_name}\" was typed; "
            f"use /fwa blacklist add."
        )

    end = getattr(war, "end_time", None)
    end_dt = getattr(end, "time", None)
    war_end_time = end_dt.isoformat() if end_dt is not None else None

    try:
        added_tag = await add_blacklisted(
            mongo, opponent_tag, opponent_name, added_by_id, added_by_name,
            "war-plans", our_clan_tag=our_tag, war_end_time=war_end_time,
        )
    except Exception as e:
        print(f"[FWA War Plans] Failed to store blacklist entry for {opponent_tag}: "
              f"{type(e).__name__}: {e}")
        return BLACKLIST_UNREADABLE_NOTE

    if not added_tag:
        return BLACKLIST_UNREADABLE_NOTE

    return f"Added {opponent_name} (#{added_tag}) to the FWA blacklist."


@fwa.register()
class WarPlans(
    lightbulb.SlashCommand,
    name="war-plans",
    description="Generate war strategy messages for different war outcomes"
):
    clan_name = lightbulb.string(
        "clan",
        "Select the FWA clan",
        autocomplete=fwa_clans  # Use the imported function directly
    )

    war_result = lightbulb.string(
        "result",
        "Select the war outcome type",
        choices=[
            lightbulb.Choice(name="Win", value="win"),
            lightbulb.Choice(name="Lose", value="lose"),
            lightbulb.Choice(name="Blacklisted", value="blacklisted"),
            lightbulb.Choice(name="Mismatch", value="mismatch")
        ]
    )

    opponent = lightbulb.string(
        "opponent",
        "Enter the opponent clan name",
        max_length=FWA_WAR_PLANS_CONFIG["max_opponent_name_length"]
    )

    @lightbulb.invoke
    @lightbulb.di.with_di
    async def invoke(
            self,
            ctx: lightbulb.Context,
            mongo: MongoClient = lightbulb.di.INJECTED,
            coc_client: coc.Client = lightbulb.di.INJECTED,
    ) -> None:
        await ctx.defer(ephemeral=True)

        # Check if user has FWA Clan Rep role
        if not ctx.member or FWA_WAR_PLANS_CONFIG["fwa_clan_rep_role_id"] not in ctx.member.role_ids:
            await ctx.respond("❌ You must have the FWA Clan Rep role to use this command.", ephemeral=True)
            return

        # Extract clan info from autocomplete selection
        # Desktop returns format: "Clan Name|#TAG|role_id"
        # Mobile might return just: "Clan Name" (display text)
        parts = self.clan_name.split("|")
        
        if len(parts) >= 3:
            # Desktop format - parse normally
            clan_display_name = parts[0]
            clan_tag = parts[1]
            clan_role_id = parts[2]
        else:
            # Mobile format - just clan name, need to look up in database
            clan_display_name = self.clan_name.strip()
            
            # Look up clan details from database
            clan_data = await mongo.clans.find_one({"name": clan_display_name, "type": "FWA"})
            if not clan_data:
                await ctx.respond(
                    f"❌ Could not find FWA clan '{clan_display_name}' in database.\n"
                    f"Please try selecting the clan again.",
                    ephemeral=True
                )
                return
            
            clan_tag = clan_data.get("tag", "")
            clan_role_id = str(clan_data.get("role_id", ""))

        # Validate role_id
        if not clan_role_id or clan_role_id == "None":
            await ctx.respond("❌ This clan doesn't have a Discord role assigned.", ephemeral=True)
            return

        # Fetch the clan to get announcement channel
        raw = await mongo.clans.find_one({"tag": clan_tag})
        if not raw:
            await ctx.respond("❌ Clan not found in database!", ephemeral=True)
            return

        db_clan = Clan(data=raw)

        # Set target channel from clan data
        target_channel = db_clan.announcement_id
        if not target_channel:
            await ctx.respond("❌ This clan doesn't have an announcement channel set!", ephemeral=True)
            return

        # Sanitize opponent name (no validation needed - allow all characters)
        opponent_name = sanitize_opponent_name(self.opponent)

        # Get author name
        author_name = ctx.member.display_name if ctx.member else ctx.user.username

        # Generate appropriate message components using templates
        templates = WarMessageTemplates()
        message_components = None

        if self.war_result == "win":
            message_components = templates.win_message(opponent_name, author_name, clan_role_id)
        elif self.war_result == "lose":
            message_components = templates.lose_message(opponent_name, author_name, clan_role_id)
        elif self.war_result == "blacklisted":
            message_components = templates.blacklisted_message(
                opponent_name, author_name, clan_role_id,
                FWA_WAR_PLANS_CONFIG["fwa_clan_rep_role_id"]
            )
        elif self.war_result == "mismatch":
            message_components = templates.mismatch_message(opponent_name, author_name, clan_role_id)

        # Get the appropriate copy text
        copy_texts = WarCopyTexts()
        copy_text = ""
        if self.war_result == "win":
            copy_text = copy_texts.win_copy(opponent_name)
        elif self.war_result == "lose":
            copy_text = copy_texts.lose_copy(opponent_name)
        elif self.war_result == "blacklisted":
            copy_text = copy_texts.blacklisted_copy(opponent_name)
        elif self.war_result == "mismatch":
            copy_text = copy_texts.mismatch_copy(opponent_name)

        # Send main message to target channel
        try:
            # Create message with components only (no content field for Components V2)
            message = await ctx.client.rest.create_message(
                channel=target_channel,  # Now uses the clan's announcement channel
                components=message_components,
                role_mentions=[int(clan_role_id)]
            )

            final_copy_text = copy_text
            if self.war_result == "blacklisted":
                blacklist_note = await _add_war_opponent_to_blacklist(
                    coc_client, mongo, clan_tag,
                    ctx.user.id, author_name, opponent_name,
                )
                final_copy_text = f"{copy_text}\n{blacklist_note}"

            # Send ephemeral response with just the copy text as plain text
            await ctx.respond(
                content=final_copy_text,
                ephemeral=True
            )

        except Exception as e:
            error_components = [
                Container(
                    accent_color=RED_ACCENT,
                    components=[
                        Text(content="## ❌ **Error Posting Message**"),
                        Text(content=f"Failed to post war message: {str(e)}"),
                        Text(content="Please check bot permissions and channel access."),
                        Media(items=[MediaItem(media="assets/Red_Footer.png")])
                    ]
                )
            ]
            await ctx.respond(components=error_components, ephemeral=True)


loader.command(fwa)
