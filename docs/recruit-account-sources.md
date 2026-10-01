# Recruitment player information: ClashKing and ClashPerk

Ticket creation, staff refresh, automatic retries, and final decisions use the
same combined lookup. Other consumers of the shared ClashKing resolver are
unchanged (including `/accounts` and Warrior Setup).

- Both providers are queried concurrently using the applicant's Discord ID.
- The union is deduplicated by normalized player tag. Reverse lookups check for
  conflicting ownership across providers; conflicts are excluded from current
  accounts and explicitly block approval until resolved at the source.
- Current names, Town Hall and clan come from the official Clash of Clans API.
- Staff Applicant context shows a three-account preview. View All Player Info
  opens eight accounts per page privately. Refresh Player Info updates the
  existing durable staff context; it does not post duplicate summaries.
- Every control rechecks recruiter/admin authorization in the configured guild.
  Applicants cannot use these controls or see the staff-only information.
- A failed source is not an empty list. Available accounts remain visible and
  prior accounts from unavailable sources are retained, labelled potentially
  stale. Approval waits for a complete, conflict-free lookup. Denial remains
  available. Existing blacklist and FWA review protections still apply.
- A ClashPerk unverified link is shown as such. It is a provider-reported link,
  not a verified ownership claim. Either provider alone can supply accounts
  when both queries succeed and the other returns no links.

## Configuration and credentials

Set `CLASHPERK_PASSKEY` in the bot's private `.env`. The existing
`CLASHKING_API_TOKEN` and `COC_API_TOKEN` remain required. Never put credentials
in MongoDB, documentation, source control, or logs.

`utils/clashperk_links.py` uses https://api.clashperk.com/v1:
`POST /auth/login` and read-only `POST /links/query`. JWTs are held only in memory,
renewed before the documented two-hour expiry, and refreshed once on a 401.
Redirects are disabled. Queries are batched at 100 identifiers; failed batches
invalidate the source result rather than masquerading as a shorter account list.

## MongoDB

No new collection or shared button-store data. The canonical ticket's
`linked_accounts.version = 2` stores current profiles, `link_sources`,
`clashperk_verified`, `clan_name`, `clan_tag`, `unavailable_sources`, and
`conflicting_tags`. Existing revision-based compare-and-swap protects concurrent
updates, and `player_tags` remains append-only for history and flags.
Existing account audit, retry, and staff-context outbox mechanisms are reused.
Access tokens and passkeys are never stored in ticket documents.

Existing open tickets acquire the combined snapshot at their next refresh or
decision; publishing updated staff context exposes the refresh control without
reopening or deciding a ticket. Closed ticket data is not bulk rewritten.

## Validation

Tests cover union/deduplication, foreign IDs, malformed payloads/tags, conflicting
owners, empty versus unavailable sources, partial-outage retention, recovery,
ClashPerk-only approval, incomplete-lookup approval blocks, credentials/401s,
batching, authorization and Discord layout limits. A read-only live lookup also
checks source access and official game profiles. No test changes provider links.

## Reviewing link conflicts during approval

Approve from a console button or `/tickets approve` presents one private review
for all conflicting accounts: **Yes — Reviewed** opens a required reason modal;
**No — Review First** leaves the ticket unchanged and links to player information.
All handlers recheck the requesting recruiter, guild and fixed 15-minute session.

The review is recorded under `linked_accounts.conflict_review` and in the bounded
`account_identity_audit` with reviewer, time, reason, tags and a fingerprint of the
applicant plus both providers' exact owner mappings. It is a ticket-local staff
review, not a change to an external link service. Conflicting tags are included
only while this exact review matches a fresh, complete lookup. Changed mappings
invalidate the review; an unavailable provider cannot be overridden this way.

Submission resumes the same approval service (or the explicitly requested
console overturn flow). Restored tags participate in historical identity, flags,
blacklist and FWA Chocolate checks. Existing decision and account revision guards
remain in place. The exact accounts explicitly confirmed in this review also satisfy the FWA
account re-review, avoiding a redundant prompt. Unrelated newly discovered
accounts still require their own review. No path approves automatically merely because a review
reason was supplied. Staff see the saved reason alongside player information.
