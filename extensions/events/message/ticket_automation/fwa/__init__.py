# extensions/events/message/ticket_automation/fwa/__init__.py
"""
FWA (Farm War Alliance) ticket automation system.
Handles FWA-specific recruitment flow including war weight checks,
FWA education, and agreement process.

Test pattern: 𝕋-𝔽𝕎𝔸
Production pattern: 𝔽𝕎𝔸 (disabled by default)
"""

from .core.fwa_manager import (
    trigger_fwa_automation,
    initialize_fwa,
    is_fwa_ticket,
    handle_fwa_text_response
)
from .core.fwa_flow import FWAFlow

__all__ = [
    'trigger_fwa_automation',
    'initialize_fwa',
    'is_fwa_ticket',
    'handle_fwa_text_response',
    'FWAFlow'
]