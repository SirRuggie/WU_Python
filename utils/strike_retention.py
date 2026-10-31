"""Retention policy, enabled only by the backup-and-restore maintenance gate."""
from datetime import timedelta
from utils.strike_store import stamp

RECORD_DAYS = 90
SNAPSHOT_DAYS = 30


def record_purge_after(row):
    return stamp(row['occurred_at']) + timedelta(days=RECORD_DAYS)


def snapshot_purge_after(row):
    return stamp(row['end_time']) + timedelta(days=SNAPSHOT_DAYS)


def protected_profile(profile):
    """Only the persistent profile owns streaks; never derive them from history."""
    return {key: value for key, value in profile.items()
            if key.startswith('streak_') or key in ('replacement_priority', 'replacement_note')}
