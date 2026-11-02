# HTTP Mongo startup route boundary

The first mongo-client-lifecycle-1 activation did not pass backend readiness.
LiveProviders normally owns a frozen mapping of validated Namespace objects;
the new startup pool passed that mapping to MongoClient's raw route_overrides
argument. Its strict validator correctly rejected the value, so the application
could not start. Earlier pool fixtures used routes={} and missed this boundary.

Convert the public normalized route values back to raw database/collection
settings at the HTTP pool boundary. The native client still validates every
setting; no environment route, namespace restriction, pool size or timeout is
relaxed. Preserve raw settings for injected fixtures and None for environment
configuration. No production configuration edit is required.

Regressions use the actual client constructor with a default LiveProviders,
normalized explicit routes, raw overrides and malformed settings. An owned Mongo
case starts the lifecycle, pings and reads the family directory through the same
pool, then closes it and removes only its fixture database. Reintroducing the
original direct normalized mapping must fail those production-shaped tests.
No live provider request, role write or notification is tested.

The failed application tag remains immutable. Wait for rollback health, direct
Claude ACCEPT and fresh release gates before a new tag/activation. Report all
forward, automatic systemd and rollback restarts honestly; never restore data.

Validation: eight related tests pass, with one opt-in skip in that run; the owned
run passes all four startup cases and stops/removes its server. Two genuine
mutants are killed (original normalized-as-raw call; silently dropping explicit
routes). A network-blocked rehearsal of all 51 configured production routes
preserves every destination and closes the actual client. Initial owned test
setup used an overlong generated database name and assumed a list instead of
the provider's public envelope; both fixture errors were corrected before the
final passing run. Frontend source is unchanged by this fix.
