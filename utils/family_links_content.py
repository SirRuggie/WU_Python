"""Pure Components V2 layout shared by published content and member controls."""
import hikari
from hikari.impl import (
    ContainerComponentBuilder as Container,
    InteractiveButtonBuilder as Button,
    MediaGalleryComponentBuilder as Media,
    MediaGalleryItemBuilder as MediaItem,
    MessageActionRowBuilder as ActionRow,
    SeparatorComponentBuilder as Separator,
    TextDisplayComponentBuilder as Text,
)
from utils.constants import WU_GOLD

DEFAULT_SECTIONS = (
    "## Roles and clan links", "Set your Town Hall and server roles.",
    "## Join a clan", "-# Only you can see your roles and links.",
)
BANNER = "assets/branding/banners/Warriors_United.gif"


def panel_components(sections=None, media=None, **_kwargs):
    sections = DEFAULT_SECTIONS if sections is None else sections
    banner = (media or {}).get("banner", BANNER)
    return [Container(accent_color=WU_GOLD, components=[
        Media(items=[MediaItem(media=banner)]),
        Text(content=sections[0]), Text(content=sections[1]),
        ActionRow(components=[Button(style=hikari.ButtonStyle.SECONDARY,
            custom_id="family_links_my_roles:", label="My roles", emoji="🎭")]),
        Separator(divider=True, spacing=hikari.SpacingType.SMALL),
        Text(content=sections[2]),
        ActionRow(components=[Button(style=hikari.ButtonStyle.SECONDARY,
            custom_id=f"family_links_{kind}_clans:", label=label, emoji=emoji)
            for kind, label, emoji in (("war", "War clans", "⚔️"),
                                      ("fwa", "FWA clans", "🏳️"),
                                      ("cwl", "CWL clans", "🏆"))]),
        Media(items=[MediaItem(media="assets/Gold_Footer.png")]),
        Text(content=sections[3]),
    ])]
