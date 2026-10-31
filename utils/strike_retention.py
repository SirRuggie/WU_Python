"""Retention policy, enabled only by the backup-and-restore maintenance gate."""
from datetime import timedelta
from utils.strike_store import stamp

from utils.strike_retention_policy import RECORD_DAYS, SNAPSHOT_DAYS, INCOMPLETE_DAYS


def record_purge_after(row):
    return stamp(row['occurred_at']) + timedelta(days=RECORD_DAYS)


def snapshot_purge_after(row):
    if row.get('manual_review_required'):
        return None
    if row.get('status') == 'resolved':
        return stamp(row['resolved_at']) + timedelta(days=SNAPSHOT_DAYS)
    if row.get('status') == 'finalized':
        return stamp(row['end_time']) + timedelta(days=SNAPSHOT_DAYS)
    if row.get('status') in ('incomplete', 'abandoned'):
        return stamp(row['end_time']) + timedelta(days=INCOMPLETE_DAYS)
    return None


def validate_record_retention(row):
    purge = record_purge_after(row)
    if (row.get('kind') == 'strike' and not row.get('revoked_at')
            and row.get('expires_at') and stamp(row['expires_at']) > purge):
        raise ValueError('Strike expiry exceeds retention; review before enabling TTL')
    return purge
