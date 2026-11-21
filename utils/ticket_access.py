"""Pure ticket handler scope shared by Discord and HTTP authorization adapters."""
TICKET_TYPES = frozenset({'main', 'fwa', 'account', 'staff'})
RECRUIT_TYPES = frozenset({'main', 'fwa'})


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def ticket_type_role_ids(config, ticket_type: str) -> frozenset[int]:
    kind = str(ticket_type or '').strip().lower()
    if kind in RECRUIT_TYPES:
        kinds = RECRUIT_TYPES
    elif kind == 'account':
        kinds = RECRUIT_TYPES | {'account'}
    elif kind == 'staff':
        kinds = {'staff'}
    else:
        return frozenset()
    return frozenset(role for item in kinds
                     if (role := _int(config.get(f'{item}_thread_recruiter_role'))))


def allowed_types_from_config(config, *, guild_id, role_ids, administrator) -> frozenset[str]:
    target = _int(config.get('ticket_target_guild_id'))
    if not target or _int(guild_id) != target:
        return frozenset()
    if administrator:
        return TICKET_TYPES
    roles = {_int(role) for role in role_ids}
    return frozenset(kind for kind in TICKET_TYPES
                     if roles & ticket_type_role_ids(config, kind))
