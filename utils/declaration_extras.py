"""Read-only member comparison, using account identities rather than owners."""


def extras_for(
    clan_tag,
    members,
    accounts,
    names,
    *,
    current_accounts=None,
    roster_marks=None,
    category="extras"
):
    roster_marks = roster_marks or {}
    assignments = {row["tag"]: row for row in accounts}
    current = {
        row["tag"]: row
        for row in (accounts if current_accounts is None else current_accounts)
    }
    result = []
    for member in members:
        if not isinstance(member.get("name"), str):
            raise ValueError("Incomplete official clan member name")
        marked = bool(roster_marks.get(member["tag"], {}).get("roster_filler"))
        th = member.get("town_hall")
        low = type(th) is int and 0 < th <= 9
        assigned_here = (
            assignments.get(member["tag"], {}).get("assigned_clan_tag") == clan_tag
        )
        if category == "fillers" and not marked:
            continue
        if category == "low_th" and not low:
            continue
        if category == "extras" and (marked or low):
            continue
        row = assignments.get(member["tag"])
        if category == "extras" and row and row.get("assigned_clan_tag") == clan_tag:
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
                "roster_filler": marked,
                "roster_filler_revision": roster_marks.get(member["tag"], {}).get(
                    "revision", 0
                ),
                "assigned_here": assigned_here,
                "assigned_clan_tag": assigned,
            }
        )
    return sorted(result, key=lambda row: (row["name"].casefold(), row["tag"]))
