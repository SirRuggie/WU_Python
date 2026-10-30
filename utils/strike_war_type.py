"""Classify war kind from complete preparation timing, independent of coc.py."""
from datetime import datetime


FRIENDLY_PREP_SECONDS = tuple(minutes * 60 for minutes in
                              (5, 15, 30, 60, 120, 240, 360, 480, 720, 960, 1200, 1440))
FRIENDLY_TOLERANCE_SECONDS = 120
REGULAR_PREP_SECONDS = 23 * 60 * 60
REGULAR_TOLERANCE_SECONDS = 45 * 60


def classify_war_type(start: datetime | None, preparation: datetime | None,
                      *, war_tag=None) -> str:
    if war_tag:
        return 'cwl'
    if start is None or preparation is None:
        return 'unknown'
    duration = (start - preparation).total_seconds()
    if duration <= 0:
        return 'unknown'
    if any(abs(duration - value) <= FRIENDLY_TOLERANCE_SECONDS
           for value in FRIENDLY_PREP_SECONDS):
        return 'friendly'
    if abs(duration - REGULAR_PREP_SECONDS) <= REGULAR_TOLERANCE_SECONDS:
        return 'regular'
    return 'unknown'
