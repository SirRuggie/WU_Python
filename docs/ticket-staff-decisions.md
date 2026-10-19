# Staff decision records

New ticket approvals and denials also post a red/green decision card in the
linked staff thread. It includes the recruit, ticket number/type, decision maker,
decision time, and the custom or standard denial reason. All mentions are disabled:
recording the recruit's identity never pings or adds them to the staff thread.

The normal decision transition creates a `resolution_effects.staff_notification`
obligation on the existing ticket document. Its state and Discord message ID are
checkpointed independently of the applicant notification. Failed delivery keeps
resolution effects incomplete and uses the existing restart-safe recovery worker.
A stable per-resolution Discord nonce and history lookup suppress repeated sends.

An archived/locked staff thread is opened to deliver the notice. Missing staff
threads follow existing missing-thread handling and are checkpointed as skipped.
Overturns append a new staff record, preserving earlier decisions. The applicant
card's existing replacement behavior is unchanged. Isolated tests use the test
thread and simulated wording, with the same isolated ticket storage.

This applies to decisions made after deployment. Previously completed decisions
are not backfilled or reannounced.

An authorized recruiter's Approve click is the account review confirmation.
At least one current linked Clash account is required. Newly discovered links,
provider warnings, and pending staff-context or identity refreshes do not require
a second click. A failed lookup may use the retained current linked snapshot;
a successful lookup returning no accounts still blocks approval. Historical
player tags alone do not count as linked accounts. Permission, blacklist, and
concurrent-decision checks still apply. Staff-context delivery retries separately.
