"""Explicit loopback endpoints for independently owned profile/role fixtures."""

from urllib.parse import urlsplit


def fixture_uri(value):
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme == "mongodb"
            and parsed.hostname == "127.0.0.1"
            and parsed.username is None
            and parsed.password is None
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and parsed.port is not None
            and 27150 <= parsed.port <= 27169
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Use an explicitly owned loopback Mongo fixture on ports 27150–27169, without credentials, database, query or fragment.")
    return f"mongodb://127.0.0.1:{parsed.port}"
