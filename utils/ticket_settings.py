"""Pure ticket-setting validation and history projections shared by adapters.

Storage, authorization, auditing and Discord transport remain with their existing
owners. These helpers preserve the ticket adapter's accepted values and defaults.
"""

FIELDS = {
    f'{kind}_{name}'
    for kind in ('main', 'fwa')
    for name in ('candidate_parent', 'staff_parent', 'thread_recruiter_role')
} | {
    'ticket_staff_viewer_role_ids',
    'ticket_inactivity_minutes',
    'ticket_archive_quiet_days',
}


def validated_settings(values):
    if not isinstance(values, dict) or set(values) - FIELDS:
        raise ValueError('Unknown ticket setting.')
    clean = {}
    for key, value in values.items():
        if key == 'ticket_staff_viewer_role_ids':
            if (not isinstance(value, list) or len(value) > 25
                    or any(not isinstance(v, str) or not v.isdigit() for v in value)):
                raise ValueError("Select valid viewer roles.")
            clean[key] = list(map(int, value))
        elif key == 'ticket_inactivity_minutes':
            if type(value) is not int or not 1440 <= value <= 525600:
                raise ValueError('Open-ticket wait must be 1 to 365 days in minutes.')
            clean[key] = value
        elif key == 'ticket_archive_quiet_days':
            if type(value) is not int or not 0 <= value <= 365:
                raise ValueError('Archive wait must be 0 to 365 days.')
            clean[key] = value
        else:
            if (not isinstance(value, str) or not value.isdigit()
                    or not 15 <= len(value) <= 22):
                raise ValueError("Select a channel or role.")
            clean[key] = int(value)
    return clean


def history_values(cfg, part):
    if part == 'timers':
        return {
            'ticket_inactivity_minutes': cfg.get('ticket_inactivity_minutes', 10080),
            'ticket_archive_quiet_days': cfg.get('ticket_archive_quiet_days', 1),
        }
    if part == 'viewers':
        return {
            'ticket_staff_viewer_role_ids': [
                str(x) for x in cfg.get('ticket_staff_viewer_role_ids', [])
            ],
        }
    return {
        f'{part}_{key}': str(cfg.get(f'{part}_{key}') or '')
        for key in ('candidate_parent', 'staff_parent', 'thread_recruiter_role')
    }
