# extensions/events/message/ticket_automation/fwa/utils/__init__.py
"""
FWA-specific utilities and constants.
"""

from .fwa_constants import (
    FWA_TICKET_PATTERN,
    FWA_TEST_PATTERN,
    FWA_STEPS,
    EXPECTED_RESPONSES,
    FWA_TIMEOUT_SECONDS
)

from .chocolate_utils import (
    normalize_tag,
    generate_chocolate_link,
    is_valid_tag
)

from .chocolate_components import (
    create_chocolate_components,
    send_chocolate_link
)

__all__ = [
    # Constants
    'FWA_TICKET_PATTERN',
    'FWA_TEST_PATTERN',
    'FWA_STEPS',
    'EXPECTED_RESPONSES',
    'FWA_TIMEOUT_SECONDS',
    # Utils
    'normalize_tag',
    'generate_chocolate_link',
    'is_valid_tag',
    # Components
    'create_chocolate_components',
    'send_chocolate_link'
]