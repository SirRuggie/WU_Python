"""Pure ticket-setting validation and history projections shared by adapters.

Storage, authorization, auditing and Discord transport remain with their existing
owners. These helpers preserve the ticket adapter's accepted values and defaults.
"""

import hashlib
import json


_RUNTIME_REVISION_KEYS = frozenset({
    "thread_name_capability_version",
    "thread_name_capability_booted_at",
    "thread_name_capability_boot_id",
    "thread_name_capability_heartbeat_at",
})


def settings_revision(cfg):
    """Fingerprint settings without the bot's ephemeral capability heartbeat.

    Keep every other key, including the native revision counter and future
    settings, so real edits and edit-then-restore races remain conflicts.
    The filtered copy leaves the shared configuration document untouched.
    """
    settings = {key: value for key, value in cfg.items()
                if key not in _RUNTIME_REVISION_KEYS}
    return hashlib.sha256(
        json.dumps(settings, sort_keys=True, default=str).encode()
    ).hexdigest()


DESK_KEYS = ('desk_channel_id', 'desk_staff_parent', 'account_thread_recruiter_role',
             'staff_thread_recruiter_role')

FIELDS = {
    f'{kind}_{name}'
    for kind in ('main', 'fwa')
    for name in ('candidate_parent', 'staff_parent', 'thread_recruiter_role')
} | {
    'ticket_staff_viewer_role_ids',
    'ticket_inactivity_minutes',
    'ticket_archive_quiet_days',
} | set(DESK_KEYS)


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
    if part == 'desk':
        return {key: str(cfg.get(key) or '') for key in DESK_KEYS}
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


DESK_REQUIRED_FIELDS = (
    ("desk_channel_id", "Warrior Desk channel"),
    ("desk_staff_parent", "Staff thread channel"),
    ("account_thread_recruiter_role", "Add account staff role"),
    ("staff_thread_recruiter_role", "Contact staff role"),
)


def desk_readiness(config, *, phase, rollout_valid=True):
    """Saved prerequisite metadata shared by HTTP and native settings adapters."""
    missing = []
    for key, label in DESK_REQUIRED_FIELDS:
        value = config.get(key)
        if key == "desk_staff_parent":
            value = value or config.get("main_staff_parent")
        try:
            valid = int(value or 0) > 0
        except (TypeError, ValueError):
            valid = False
        if not valid:
            missing.append({"key": key, "label": label})
    if not rollout_valid or phase not in {"thread_default", "thread_only"}:
        missing.append({"key": "", "label": "Thread-default or thread-only rollout"})
    return {"ready": not missing, "missing": missing}
