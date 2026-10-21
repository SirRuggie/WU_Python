"""Interpret persisted checks conservatively for the family reminder overview."""
from datetime import datetime, timezone

STALE_SECONDS = 180


def timestamp(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def health(config, status, delivery, now):
    if not config:
        return 'not_configured', 'Not configured', 'Choose a channel and reminder times to get started.'
    if not config.get('enabled'):
        return 'off', 'Off', 'Automatic reminders are disabled.'
    if not config.get('channel_id'):
        return 'attention', 'Channel needed', 'Choose a reminder channel.'
    if delivery and delivery.get('status') in ('uncertain', 'sending', 'failed'):
        return 'attention', 'Check delivery', 'The last scheduled delivery was not confirmed. Check the channel before taking action.'
    status = status or {}
    checked = timestamp(status.get('checked_at'))
    updated = timestamp(config.get('updated_at'))
    # A check from before the settings changed does not verify the new settings.
    if checked is None or (updated and checked < updated):
        if updated and 0 <= (now-updated).total_seconds() <= STALE_SECONDS:
            return 'pending', 'Awaiting check', 'Waiting for the bot to check these settings.'
        return 'attention', 'No recent check', 'No check has confirmed the current settings. Check bot availability.'
    age = (now-checked).total_seconds()
    if age > STALE_SECONDS or age < -60:
        return 'attention', 'Check overdue', 'The latest check is out of date. Check bot availability.'
    if status.get('error'):
        return 'attention', 'Check failed', status.get('detail') or 'The bot could not check or deliver reminders.'
    return 'tracking', 'Monitoring', status.get('detail') or 'The bot is monitoring this clan.'
