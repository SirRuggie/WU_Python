# extensions/events/message/ticket_automation/utils/__init__.py
"""
Utility modules for ticket automation.
"""

from .constants import (
    RECRUITMENT_STAFF_ROLE,
    LOG_CHANNEL_ID,
    REMINDER_DELETE_TIMEOUT,
    REMINDER_TIMEOUT,
    TIMEZONE_CONFIRMATION_TIMEOUT,
)

from .helpers import (
    format_user_mention,
    calculate_time_difference,
    get_current_timestamp
)

from .validators import (
    validate_user_id,
    is_automation_active,
    validate_channel_id,
    is_friend_time_bot,
    validate_timestamp,
    is_valid_ticket_type,
    validate_questionnaire_step
)

__all__ = [
    # Constants
    'RECRUITMENT_STAFF_ROLE',
    'LOG_CHANNEL_ID',
    'REMINDER_DELETE_TIMEOUT',
    'REMINDER_TIMEOUT',
    'TIMEZONE_CONFIRMATION_TIMEOUT',
    'QUESTIONNAIRE_QUESTIONS',
    'AGE_RESPONSES',
    # Helpers
    'format_user_mention',
    'calculate_time_difference',
    'get_current_timestamp',
    # Validators
    'validate_user_id',
    'is_automation_active',
    'validate_channel_id',
    'is_friend_time_bot',
    'validate_timestamp',
    'is_valid_ticket_type',
    'validate_questionnaire_step'
]