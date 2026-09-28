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


async def start_url(rest, document: str, guild_id: int) -> str:
    """Jump to the destination's first message, resolving again after reposts."""
    import asyncio
    import logging

    route = route_for(document, guild_id)
    if route is None:
        raise ValueError("This onboarding step is not configured for this server.")
    channel_id = route[1]
    url = f"https://discord.com/channels/{guild_id}/{channel_id}"
    try:
        # `after` makes Hikari iterate oldest first. Only retrieve one message.
        async with asyncio.timeout(3):
            messages = await rest.fetch_messages(channel_id, after=0).limit(1)
        if messages:
            return f"{url}/{int(messages[0].id)}"
    except Exception:
        # Access has already been granted; history lookup must not break it.
        logging.getLogger(__name__).warning(
            "Could not resolve Gauntlet first message for channel %s", channel_id
        )
    return url
