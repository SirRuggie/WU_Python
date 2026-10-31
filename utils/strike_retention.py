"""Retention policy, enabled only by the backup-and-restore maintenance gate."""
from datetime import timedelta
from utils.strike_store import stamp

RECORD_DAYS = 90
SNAPSHOT_DAYS = 30


def record_purge_after(row):
    return stamp(row['occurred_at']) + timedelta(days=RECORD_DAYS)


def snapshot_purge_after(row):
    return stamp(row['end_time']) + timedelta(days=SNAPSHOT_DAYS)


def validate_record_retention(row):
    purge = record_purge_after(row)
    if (row.get('kind') == 'strike' and not row.get('revoked_at')
            and row.get('expires_at') and stamp(row['expires_at']) > purge):
        raise ValueError('Strike expiry exceeds retention; review before enabling TTL')
    return purge
