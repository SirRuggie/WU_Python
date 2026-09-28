"""Server-local Gauntlet roles and destinations during the server transition."""
NEW_GUILD_ID = 644963518025826315
LEGACY_GUILD_ID = 1078723854303756298

# Keep the original recruitment server operational until its retirement.
ROUTES = {
    NEW_GUILD_ID: {
        "join-family": (1551011479577165844, 1547241886954168430),
        "about-us": (1553110276251979937, 1547242610819604560),
        "strike-system": (1553110508746448956, 1547242699873325116),
        "family-particulars": (1553110621711634502, 1547242779711766528),
    },
    LEGACY_GUILD_ID: {
        "about-us": (1078723854303756301, 1078723854316355602),
        "strike-system": (1078723854303756302, 1078723854316355603),
        "family-particulars": (1078723854303756303, 1078723854635110530),
    },
}


def route_for(document: str, guild_id: int | None) -> tuple[int, int] | None:
    return ROUTES.get(int(guild_id or 0), {}).get(document)
