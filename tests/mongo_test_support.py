"""Safety boundaries for optional real-Mongo ticket regressions.

These tests intentionally share the dedicated ``wubot_test`` database.  They
must never infer a database from the URI or remove a database as cleanup.
"""

import os
from urllib.parse import urlsplit
import uuid


TEST_DATABASE = "wubot_test"
COLLECTION_PREFIX = "ticket_real_mongo_"


def test_mongodb_uri():
    """Return the explicitly scoped test URI, or ``None`` when not configured.

    The database path is validated before a client is constructed so a copied
    production URI fails safely instead of being used by an optional test.
    """
    uri = os.getenv("TICKET_TEST_MONGODB_URI")
    if not uri:
        return None

    parsed = urlsplit(uri)
    if (
        parsed.scheme not in {"mongodb", "mongodb+srv"}
        or not parsed.netloc
        or parsed.path != f"/{TEST_DATABASE}"
        or parsed.fragment
    ):
        raise ValueError(
            "TICKET_TEST_MONGODB_URI must be a MongoDB URI explicitly naming "
            f"the {TEST_DATABASE!r} database"
        )
    return uri


def test_collection_name(label: str) -> str:
    """Create a UUID-scoped collection name for one real-Mongo test run."""
    if not label.replace("_", "").isalnum():
        raise ValueError("test collection labels may contain only letters, digits, and underscores")
    return f"{COLLECTION_PREFIX}{label}_{uuid.uuid4().hex}"


async def cleanup_test_collections(database, collection_names) -> None:
    """Drop only generated collections, never the containing database."""
    names = tuple(collection_names)
    if any(not name.startswith(COLLECTION_PREFIX) for name in names):
        raise ValueError("refusing to clean up a collection outside the test prefix")
    for name in names:
        await database.drop_collection(name)


async def verify_test_mongodb_access(client) -> None:
    """Require the narrowly scoped role before a real-Mongo regression writes."""
    status = await client.admin.command("connectionStatus")
    roles = {
        (role.get("role"), role.get("db"))
        for role in status.get("authInfo", {}).get("authenticatedUserRoles", [])
    }
    expected_roles = {("readWrite", TEST_DATABASE)}
    if roles != expected_roles:
        raise RuntimeError(
            "TICKET_TEST_MONGODB_URI must authenticate a user with only the "
            f"readWrite role on {TEST_DATABASE}"
        )
