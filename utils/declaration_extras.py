"""Read-only member comparison, using account identities rather than owners."""


def extras_for(clan_tag, members, accounts, names, *, current_accounts=None):
    assignments = {row["tag"]: row for row in accounts}
    current = {
        row["tag"]: row
        for row in (accounts if current_accounts is None else current_accounts)
    }
    result = []
    for member in members:
        if not isinstance(member.get("name"), str):
            raise ValueError("Incomplete official clan member name")
        row = assignments.get(member["tag"])
        if row and row.get("assigned_clan_tag") == clan_tag:
            continue
        row = current.get(member["tag"])
        assigned = row.get("assigned_clan_tag") if row else None
        context = (
            "Assigned to "
            + (row.get("assigned_clan_name") or names.get(assigned) or assigned)
            if assigned
            else "Signed up, unplaced" if row else "Not signed up"
        )
        result.append(
            {
                "tag": member["tag"],
                "name": member["name"],
                "town_hall": member.get("town_hall"),
                "context": context,
                "assigned_clan_tag": assigned,
            }
        )
    return sorted(result, key=lambda row: (row["name"].casefold(), row["tag"]))
