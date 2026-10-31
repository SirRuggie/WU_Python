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


def validate_record_retention(row):
    purge = record_purge_after(row)
    if (row.get('kind') == 'strike' and not row.get('revoked_at')
            and row.get('expires_at') and stamp(row['expires_at']) > purge):
        raise ValueError('Strike expiry exceeds retention; review before enabling TTL')
    return purge
