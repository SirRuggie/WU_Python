# Legacy ticket welcome delivery

Decision 239 Part C (D4): each initial legacy ticket-channel message now has a
fixed Discord nonce derived from its channel-ticket ID and durable delivery step.
This applies to both Main and FWA welcome messages and questionnaires in
`extensions/events/channel/ticket_channel_monitor.py`. It does not change the
separate v2 thread-ticket delivery system described in
[ticket-console-operations.md](ticket-console-operations.md).

The nonce is `tw-<channel snowflake>-w` for `welcome_sent` and
`tw-<channel snowflake>-q` for `questionnaire_sent`. It is at most 25 characters,
including a full uint64 snowflake. The mapping is deterministic across processes;
tickets and message steps have distinct identities. Invalid channel IDs or
unknown steps are rejected before a send.

Hikari 2.6.0's public `create_message` accepts `nonce`. Its implementation sends
that value through `_build_message_payload`, which adds `enforce_nonce: true`
for a nonempty nonce. There is no public `enforce_nonce` keyword to pass.
The regression exercises the installed SDK serializer with its request boundary
mocked, proving the outgoing nonce and enforcement field without making a
network request.

The existing three-attempt retry limit and delay remain unchanged. A timeout
after Discord may have accepted a POST reuses the same nonce on every attempt;
a resumed invocation of the same ticket/step also reuses it. Cancellation still
propagates without retry. Message content, components, destination, mention
settings, atomic claim/lease and durable delivery checkpoints are unchanged.

This protects the short retry window using Discord's nonce enforcement; it is
not a promise of indefinite deduplication after long downtime. The existing
saved `welcome_sent`/`questionnaire_sent` checkpoints remain authoritative for
completed steps. No storage migration or data backfill is introduced.

Tests use fake REST responses and isolated fixture state. Simulated acceptance
followed by lost responses proves stable request identity and the SDK wire
field, not live Discord delivery or a measured reduction in production pings.
No production duplicate incident was established by this change.
