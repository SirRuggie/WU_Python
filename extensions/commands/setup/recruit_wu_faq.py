"""Shared Family Rules and WU FAQ builders; no commands or delivery side effects."""

from hikari.impl import ContainerComponentBuilder as Container
from hikari.impl import TextDisplayComponentBuilder as Text

from utils.constants import WU_GOLD, WU_GREEN, WU_RED
from utils.info_channel_content import clan_lines, family_rules_sections, wu_faq_sections


def build_family_rules(sections=None, *, media=None, action_id="preview", preview=False):
    del media, action_id, preview
    heading, body = family_rules_sections(sections)
    return [Container(accent_color=WU_RED, components=[Text(content=heading), Text(content=body)])]


def build_wu_faq(sections=None, *, media=None, action_id="preview", preview=False,
                 family_rules=None, clans=None):
    del media, action_id, preview
    fields = wu_faq_sections(sections)
    from utils.gauntlet_content import faq_type_body, subtopic
    import hikari
    clan_components = [Text(content=fields[4])]
    for position, (index, kind) in enumerate(((5, "Tactical"), (6, "Flexible Fun"), (7, "FWA"))):
        if position:
            clan_components.append(hikari.impl.SeparatorComponentBuilder(divider=True, spacing=hikari.SpacingType.SMALL))
        body = faq_type_body(kind, fields[index])
        if clans is not None:
            body += "\n" + clan_lines(clans, kind)
        clan_components.append(Text(content=subtopic(kind, body)))
    clan_components.append(Text(content=fields[8]))
    return [
        Container(accent_color=WU_GOLD, components=[Text(content=fields[2]), Text(content=fields[3])]),
        Container(accent_color=WU_GREEN, components=clan_components),
        *build_family_rules(family_rules),
        Container(accent_color=None, components=[Text(content=fields[0]), Text(content=fields[1])]),
    ]
