import lightbulb
import hikari
import logging

from extensions.commands.fwa import loader, fwa
from utils.constants import BLUE_ACCENT, GOLD_ACCENT, GREEN_ACCENT, RED_ACCENT

from hikari.impl import (
    ContainerComponentBuilder as Container,
    TextDisplayComponentBuilder as Text,
    SeparatorComponentBuilder as Separator,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
)

from utils import war_weight
from utils.mongo import MongoClient

WAR_WEIGHT_RANGES = war_weight.DEFAULT_RANGES


def determine_town_hall(total_weight: int, ranges=None) -> tuple[int | None, str, int]:
    """
    Determine town hall level from total war weight.
    Returns: (th_level, status, color)
    Status can be: 'exact', 'below', 'above', 'between'
    """
    ranges = ranges or WAR_WEIGHT_RANGES
    levels = sorted(ranges)
    # Check configured bounds
    if total_weight < ranges[levels[0]]["min"]:
        return None, "below", RED_ACCENT

    # Check configured maximum
    if total_weight > ranges[levels[-1]]["max"]:
        return None, "above", RED_ACCENT

    # Find exact match
    for th_level, range_data in ranges.items():
        if range_data["min"] <= total_weight <= range_data["max"]:
            return th_level, "exact", GREEN_ACCENT

    # Find between ranges
    for th_level in levels:
        if total_weight < ranges[th_level]["min"]:
            return levels[levels.index(th_level) - 1], "between", GOLD_ACCENT

    return None, "unknown", RED_ACCENT


def get_th_emoji(th_level, config=None, available=()):
    return war_weight.emoji_for(th_level, config or war_weight.defaults(), available)


def calculate_position_in_range(weight: int, th_level: int, ranges=None) -> int:
    """Calculate percentage position within TH range."""
    ranges = ranges or WAR_WEIGHT_RANGES
    if th_level not in ranges:
        return 0

    range_data = ranges[th_level]
    range_size = range_data["max"] - range_data["min"]
    position = weight - range_data["min"]
    return int((position / range_size) * 100)


def format_weight_reference_guide(current_weight: int, current_th: int | None, config=None, available=()) -> str:
    """Format the complete weight reference guide."""
    config = config or war_weight.defaults()
    lines = []

    for th_level, range_data in sorted(war_weight.ranges(config).items(), reverse=True):
        if th_level < config["minimum_th"]:
            continue
        emoji = get_th_emoji(th_level, config, available)
        display = range_data["display"]

        # Highlight current TH level
        if th_level == current_th:
            lines.append(f"{emoji} **{display} (TH{th_level})** ← You are here")
        else:
            lines.append(f"{emoji} {display} (TH{th_level})")

    return "\n".join(lines)


def get_upgrade_info(weight: int, th_level: int | None, ranges=None) -> str:
    """Get information about upgrading to next TH level."""
    ranges = ranges or WAR_WEIGHT_RANGES
    if th_level is None or th_level >= max(ranges):
        return ""

    next_th = min(th for th in ranges if th > th_level)
    if next_th in ranges:
        next_min = ranges[next_th]["min"]
        weight_needed = next_min - weight
        if weight_needed > 0:
            return f"• {weight_needed:,} weight away from TH{next_th} range"

    return ""


@fwa.register()
class WeightCommand(
    lightbulb.SlashCommand,
    name="weight",
    description="Calculate war weight from storage value (automatically multiplies by 5)",
):
    weight = lightbulb.integer(
        "storage-weight",
        "Single storage weight value (will be multiplied by 5)",
        min_value=1,
        max_value=100000
    )

    @lightbulb.invoke
    async def invoke(self, ctx: lightbulb.Context, bot: hikari.GatewayBot = lightbulb.di.INJECTED, mongo: MongoClient = lightbulb.di.INJECTED) -> None:
        await ctx.defer(ephemeral=True)

        config = await war_weight.load(mongo, ctx.guild_id)
        ranges = war_weight.ranges(config)
        lowest, highest = min(ranges), max(ranges)
        available = list(bot.cache.get_emojis_view().values())
        # Application emojis are not in the gateway guild emoji cache.
        me = bot.get_me() if hasattr(bot, "get_me") else None
        if me is not None:
            try:
                available.extend(await bot.rest.fetch_application_emojis(me.id))
            except hikari.HTTPError:
                logging.getLogger(__name__).warning("Application emoji lookup failed; using cached/fallback Town Hall emojis")

        # Calculate total weight (multiply by 5)
        total_weight = self.weight * 5

        # Determine town hall and status
        th_level, status, color = determine_town_hall(total_weight, ranges)

        # Build status message
        if status == "below":
            status_msg = f"⚠️ **Below TH{lowest} range**\nThis weight is lower than the configured minimum ({ranges[lowest]['min']:,})."
            th_display = f"Below TH{lowest}"
        elif status == "above":
            status_msg = f"⚠️ **Above TH{highest} range**\nThis weight exceeds the maximum configured range."
            th_display = f"Above TH{highest}"
        elif status == "between":
            if th_level and th_level < highest:
                next_th = min(th for th in ranges if th > th_level)
                status_msg = f"📊 **Between TH{th_level} and TH{next_th}**"
                th_display = f"TH{th_level}-{next_th} Gap"
            else:
                status_msg = "📊 **In transition range**"
                th_display = "Transition"
        else:  # exact
            status_msg = f"✅ **Town Hall {th_level} Confirmed**"
            th_display = f"Town Hall {th_level}"
            if th_level in ranges:
                range_data = ranges[th_level]
                status_msg += f"\nWeight Range: {range_data['min']:,} - {range_data['max']:,}"

        # Build additional info_hub
        additional_info = []

        # Add upgrade info_hub if applicable
        if th_level and status == "exact":
            upgrade_info = get_upgrade_info(total_weight, th_level, ranges)
            if upgrade_info:
                additional_info.append(upgrade_info)

            # Add position in range
            position = calculate_position_in_range(total_weight, th_level, ranges)
            additional_info.append(f"• {position}% through TH{th_level} weight range")

        # Add FWA suitability with separator
        if total_weight >= 56000:  # Only show FWA info for TH9+
            additional_info.append("")  # Add empty line for separator
            if total_weight < 115000:
                additional_info.append("❌ **War Weight not suitable for FWA Wars.**")
                additional_info.append("**Minimum weight requirement = 115,000.**")
                additional_info.append("**Recommend a Flexible Fun Clan.**")
            else:
                additional_info.append("✅ **Suitable weight for FWA clan wars**")

        # Build the response components
        components = [
            Container(
                accent_color=color,
                components=[
                    Text(content="## ⚖️ **FWA War Weight Calculator**"),
                    Separator(divider=True),
                    Text(content=(
                        f"**Storage Weight:** {self.weight:,}\n"
                        f"**Total War Weight:** {self.weight:,} × 5 = {get_th_emoji(th_level, config, available)} **{total_weight:,}**\n\n"
                        f"{status_msg}"
                    )),
                ]
            ),
            Container(
                accent_color=BLUE_ACCENT,
                components=[
                    Text(content=f"### 📊 **War Weight Reference Guide (TH{config['minimum_th']}–TH{highest})**"),
                    Text(content=format_weight_reference_guide(total_weight, th_level, config, available)),
                ]
            )
        ]

        # Add additional info container if we have any
        if additional_info:
            # Build components for additional info
            additional_components = [Text(content="### 📈 **Additional Information**")]
            
            # Process additional info items
            for info in additional_info:
                if info == "":  # Empty string indicates separator
                    additional_components.append(Separator(divider=True))
                else:
                    additional_components.append(Text(content=info))
            
            additional_components.append(Media(items=[MediaItem(media="assets/Gold_Footer.png")]))
            
            components.append(
                Container(
                    accent_color=GOLD_ACCENT,
                    components=additional_components
                )
            )
        else:
            # Add footer to last container
            components[-1].components.append(
                Media(items=[MediaItem(media="assets/Blue_Footer.png")])
            )

        # Send to channel without replying
        await bot.rest.create_message(
            channel=ctx.channel_id,
            components=components
        )

        # Delete the ephemeral "thinking" message
        await ctx.interaction.delete_initial_response()


loader.command(fwa)