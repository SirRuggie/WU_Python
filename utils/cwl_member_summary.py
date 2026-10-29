"""Read-only member timing text; Discord renders timestamps in each viewer's zone."""
from datetime import datetime, timezone


def timing_lines(season, published=False, now=None):
    if published:
        return []
    try:
        deadline = datetime.fromisoformat(season['signup_deadline']).astimezone(timezone.utc)
        placement = datetime.fromisoformat(season['placements_by']).astimezone(timezone.utc)
    except (KeyError, TypeError, ValueError):
        return []
    if placement < (now or datetime.now(timezone.utc)):
        return ['Taking a little longer than usual · check back soon']
    end, ready = int(deadline.timestamp()), int(placement.timestamp())
    if season.get('signup_open') and season.get('status') == 'draft':
        return [f'Signups close <t:{end}:f> · <t:{end}:R>', f"You'll see your clan by <t:{ready}:f>."]
    return [f"Signups closed · you'll see your clan by <t:{ready}:f> · <t:{ready}:R>"]
