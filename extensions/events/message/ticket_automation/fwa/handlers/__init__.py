# extensions/events/message/ticket_automation/fwa/handlers/__init__.py
"""
FWA-specific handlers for each step of the FWA recruitment flow.
"""

from . import (
    war_weight,
    fwa_explanation,
    lazy_cwl,
    agreement,
    completion
)

__all__ = [
    'war_weight',
    'fwa_explanation',
    'lazy_cwl',
    'agreement',
    'completion'
]