"""Pure ticket handler scope shared by Discord and HTTP authorization adapters."""
TICKET_TYPES = frozenset({'main', 'fwa', 'account', 'staff'})
RECRUIT_TYPES = frozenset({'main', 'fwa'})


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0



def account_role_value(config, clan):
    """Resolve a new account handler without rewriting older configuration.

    An explicitly present new value, including an invalid/empty value, wins;
    validation must not silently substitute another role for an admin's edit.
    """
    if clan not in RECRUIT_TYPES:
        raise ValueError("Select Main clan or FWA clan.")
    key = f"account_{clan}_thread_recruiter_role"
    if key in config:
        return config[key]
    return config.get("account_thread_recruiter_role") or config.get(f"{clan}_thread_recruiter_role")

def ticket_type_role_ids(config, ticket_type: str) -> frozenset[int]:
    kind = str(ticket_type or '').strip().lower()
    if kind in RECRUIT_TYPES:
        kinds = RECRUIT_TYPES
    elif kind == 'account':
        return frozenset({_int(account_role_value(config, clan)) for clan in RECRUIT_TYPES}
                         | {_int(config.get(f'{clan}_thread_recruiter_role')) for clan in RECRUIT_TYPES}) - {0}
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
