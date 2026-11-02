"""Shared pure CWL location rules; no transport or storage access."""


def outside_family(account, family, hosts):
    clan = account.get("current_clan_tag")
    return bool(
        account.get("current_clan_status") == "current"
        and clan
        and family is not None
        and clan not in family
        and clan not in hosts
    )


def arrival_status(account):
    assigned = account.get("assigned_clan_tag")
    if not assigned:
        return "unassigned"
    if account.get("current_clan_status") != "current":
        return "unknown"
    return "arrived" if account.get("current_clan_tag") == assigned else "missing"
