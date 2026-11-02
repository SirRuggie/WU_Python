"""Application-owned async Mongo pool for HTTP adapters and their workers.

The synchronous dashboard durability pool is intentionally separate: SQLite
transactions publish synchronously. Neither pool is created per request.
"""

import os

from utils.mongo import MongoClient

APP_NAME = "wu-dashboard-http"
MAX_POOL_SIZE = 20


def get_client(app):
    """Return this app's pool, constructing once without yielding to a competitor."""
    client = app.get("dashboard_mongo")
    if client is not None:
        return client
    provider = app.get("providers")
    uri = getattr(provider, "mongo_uri", None)
    if uri is None:
        uri = os.getenv("MONGODB_URI", "").strip()
    if not uri:
        return None
    client = MongoClient(
        uri,
        route_overrides=getattr(provider, "routes", None),
        appName=APP_NAME,
        maxPoolSize=MAX_POOL_SIZE,
        serverSelectionTimeoutMS=5000,
        timeoutMS=15000,
    )
    app["dashboard_mongo"] = client
    return client


async def lifecycle(app):
    """Start before consumers and close after every consumer has stopped."""
    app["dashboard_mongo"] = None
    provider = app.get("providers")
    bind = getattr(provider, "bind_mongo", None)
    # Disconnected fixtures must not initialize a pool from ambient credentials.
    # Their explicitly exercised/injected adapters can still request a fake pool.
    try:
        if not app.get("dev_fixture") or getattr(provider, "mongo_uri", None):
            client = get_client(app)
            if bind is not None:
                bind(client)
        yield
    finally:
        client = app.get("dashboard_mongo")
        if bind is not None:
            bind(None)
        if client is not None:
            await client.close()
        app["dashboard_mongo"] = None
