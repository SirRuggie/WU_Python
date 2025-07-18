# extensions/events/message/ticket_automation/handlers/__init__.py
"""Question handlers for different types of questionnaire questions"""

from . import (
    interview_selection,
    attack_strategies,
    clan_expectations,
    discord_skills,
    age_bracket,
    timezone,
    completion
)

__all__ = [
    'interview_selection',
    'attack_strategies',
    'clan_expectations',
    'discord_skills',
    'age_bracket',
    'timezone',
    'completion'
]