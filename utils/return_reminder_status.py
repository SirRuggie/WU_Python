"""Read-only presentation of persisted home-clan return reminder settings.

Scheduled describes configuration, not proof that the worker is healthy or that
Discord accepted a message. This module never changes scheduling or storage.
"""
from datetime import datetime, timedelta, timezone


def _date(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def return_status(current, section, *, now=None):
    now = _date(now) or datetime.now(timezone.utc)
    if not current:
        return dict(state='not_saved', label='No saved list', players=0,
                    expires_at=None, last_sent_at=None, every_minutes=None)
    reminders = current.get('reminders') or {}
    expiry = _date(current.get('expires_at'))
    started = _date(reminders.get('started_at'))
    if section == 'FWA' and started:
        expiry = min(expiry, started + timedelta(days=7)) if expiry else started + timedelta(days=7)
    if expiry and expiry <= now:
        state, label = 'expired', 'Window ended'
    elif section == 'MAIN':
        state, label = 'manual', 'Manual sends'
    elif reminders.get('enabled'):
        state, label = 'scheduled', 'Scheduled'
    elif started:
        state, label = 'paused', 'Paused'
    else:
        state, label = 'idle', 'Not started'
    last = _date(reminders.get('last_sent_at'))
    return dict(state=state, label=label, players=len(current.get('players') or []),
                expires_at=expiry.isoformat() if expiry else None,
                last_sent_at=last.isoformat() if last else None,
                every_minutes=(reminders.get('every_minutes') or 60) if section == 'FWA' else None)
