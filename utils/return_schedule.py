"""Pure return-window validation shared by HTTP, storage, and the bot worker."""
from datetime import datetime, timedelta, timezone


def utc(value):
    if not isinstance(value, datetime):
        return None
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str) or len(value) > 40:
        raise ValueError('Choose a start and end date with a timezone.')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise ValueError('Choose valid start and end dates.') from None
    if parsed.tzinfo is None:
        raise ValueError('Dates must include a timezone.')
    return parsed.astimezone(timezone.utc)


def validate_window(start, end, current=None, *, now=None):
    start, end = parse_date(start), parse_date(end)
    now = utc(now) or datetime.now(timezone.utc)
    if end <= start or end <= now:
        raise ValueError('End must be after the start and still in the future.')
    if end - start > timedelta(days=7):
        raise ValueError('Return reminders can run for up to seven days.')
    if current:
        expiry = utc(current.get('expires_at'))
        started = utc((current.get('reminders') or {}).get('started_at'))
        # Changing dates must not extend a window that has already started.
        if started and started <= now and end > started + timedelta(days=7):
            raise ValueError('This clan’s original seven-day window ends sooner. Choose an earlier end.')
        if expiry and end > expiry:
            raise ValueError('End must be on or before this saved list’s seasonal cutoff.')
    return start, end


def window_end(settings):
    bounds = [utc(settings.get('schedule_end_at'))]
    started = utc(settings.get('started_at'))
    if started:
        bounds.append(started + timedelta(days=7))
    return min(value for value in bounds if value is not None) if any(bounds) else None


def before_start(settings, now):
    start = utc(settings.get('schedule_start_at'))
    return bool(start and now < start)
