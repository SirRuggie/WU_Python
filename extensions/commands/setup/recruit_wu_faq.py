"""Shared Family Rules and WU FAQ builders; no commands or delivery side effects."""

from hikari.impl import ContainerComponentBuilder as Container
from hikari.impl import TextDisplayComponentBuilder as Text

from utils.constants import WU_GOLD
from utils.info_channel_content import family_rules_sections, validate_fields
from utils.info_channel_defaults import WU_FAQ_QUESTIONS


def build_family_rules(sections=None, *, media=None, action_id="preview", preview=False):
    del media, action_id, preview
    heading, body = family_rules_sections(sections)
    return [Container(accent_color=WU_GOLD, components=[Text(content=heading), Text(content=body)])]


def build_wu_faq(sections=None, *, media=None, action_id="preview", preview=False, family_rules=None):
    del media, action_id, preview
    questions = list(WU_FAQ_QUESTIONS if sections is None else sections)
    validate_fields(questions, 2, "WU FAQ")
    return [
        *build_family_rules(family_rules),
        Container(accent_color=WU_GOLD, components=[Text(content=questions[0]), Text(content=questions[1])]),
    ]
