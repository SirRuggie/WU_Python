# Test credential isolation

Decision 239 Part B (D2): ordinary pytest runs use fixture data only. The root
pytest configuration removes live credential environment variables before test
module collection and again in an autouse session fixture. Tests can install fake
values with monkeypatch. The removed names are listed in `conftest.py`; values
are never logged. This guard is not a general network sandbox.

`utils.gold_loot` does not read `.env`. The bot already loads its environment in
`main.py`; the gold-loot CLI loads the root `.env` once when executed. Importing
either gold-loot module does not load the environment.

Optional real-Mongo ticket regressions require **both** `WU_REAL_MONGO_TESTS=1` and
`TICKET_TEST_MONGODB_URI`. The URI must name `wubot_test`; the existing access
check requires a user with only `readWrite` on that database before any writes.
Never reuse a production cluster or credential. The opt-in deliberately preserves
credentials for this exceptional run. Do not set it for ordinary regression runs.
No real-Mongo connection is needed to test these boundaries: use fake URI values,
client sentinels, and mocked authorization responses.

The LazyCWL architecture scan reads tracked Python paths from `git ls-files -z`,
so ignored local checkouts and untracked copies do not affect its result. A
fixture Git repository tests that boundary without modifying the working index.

This change does not migrate data, change endpoints, or alter dashboard behavior.

## Credential inventory and independent regression (239 rework 11)

The explicit inventory includes both `MONGODB_URI` and every tracked optional
`MONGO_URI`/`MONGODB_URI` name: ticket, LazyCWL, activity, activity restore,
startup, campaign reads, cursor tests, declaration and weights guard. The
previous guard omitted `WU_DECLARATION_TEST_MONGO_URI`,
`WU_WEIGHTS_GUARD_MONGO_URI` and `WU_ACTIVITY_RESTORE_MONGO_URI`; these are now
cleared before module collection. Snapshot/receipt/catch-up activators and the
optional recovery Mongo binary are cleared too, so inherited test switches
cannot activate real-service tests in a normal run.

Other cleared credentials include Discord/OAuth/bridge/push, Clash providers,
BAND access and private calendar URLs, R2/AWS keys, Restic password inputs and
the private backup heartbeat URL. Standard AWS session-token and Restic password
variants are included conservatively for inherited subprocess environments.
Public identifiers, asset URLs, evidence output paths and routing configuration
are not credentials. This is an explicit policy: add new credential inputs to
`conftest.py` and the independently written expected-name test inventory.

A static regression scans all tracked Python sources for Mongo URI names and
requires inventory coverage. A separate subprocess collects copies of the four
actual declaration/weights/activity optional-test modules with independent fake
URI sentinels and both Mongo constructors blocked. All captured URI values must
be absent, tests must skip, and constructor attempts must remain zero. Its
negative control removes the exact three previously omitted names and must fail
during collection, without constructing a client. These tests do not obtain
production configuration or connect to Mongo. Explicit `WU_REAL_MONGO_TESTS=1`
preserves the intended variables; the ticket URI/database and dedicated-user
role validation remain independent requirements.
