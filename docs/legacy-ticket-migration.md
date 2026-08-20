# Legacy ticket migration — cloning old tickets into threads

**Status: designed, not built.** Captures decisions made during console review
(2026-08-17 to 2026-08-20) that were discussed in chat but never written down
until now — that gap is the reason this file exists.

## 1. What this is

A manual, one-ticket-at-a-time backfill command: point it at an old
channel-based ticket (in this server or another recruitment server the bot is
also in), and it recreates that ticket as a thread pair in **one target
server**, visually cloned to look like the original conversation. Once a
ticket has been backfilled, it's searchable from the unified
[ticket-console.md](ticket-console.md) like any live ticket, and the old
channel/server can eventually be retired.

This is separate from [thread-ticketing-proposal.md](thread-ticketing-proposal.md)
§3.5's "361 existing documents" migration. That section moves **Mongo
documents** for this server's own tickets into the unified schema — a data
migration, zero Discord writes. This doc covers recreating **Discord message
content** for tickets that predate or live outside that migration, including
ones from other recruitment servers being consolidated. The two are
independent; a ticket can go through one, the other, or both.

## 2. Decisions

| # | Decision |
|---|---|
| 1 | Single target server. No cross-server thread mirroring — if source tickets live in other guilds, only their *data* gets unified (via the Mongo lookup record, §5); the recreated Discord threads live in one place. |
| 2 | Recreation is a **clone, not a legitimate copy** — messages are posted via webhook with the original author's name/avatar, not actually sent by them. User explicitly does not need real authorship or ping history preserved. |
| 3 | Every backfilled ticket gets **both** a public thread and a staff thread, matching the live system's structure going forward — not just a single thread. |
| 4 | No full message content stored in Mongo. The bot copies content directly from source channel to destination thread; Mongo only gets a small lookup record so search can find the thread (see §5). |
| 5 | Not speed-sensitive. Run one ticket at a time, verify, then continue — no batch/parallel requirement. |
| 6 | Every new thread pair is **archived immediately** after creation, not left open. Required by the thread-count math in §6, not optional. |
| 7 | Pilot first: backfill 1-2 tickets, confirm they're still searchable and openable while archived, before running the rest (~1,500). |

## 3. Per-ticket shape

Mirrors the live thread-ticketing structure so old and new tickets are
indistinguishable in the console once backfilled:

- **Public thread** — clone of the original ticket channel's message history.
- **Staff thread** — created alongside it (empty, or seeded with a short
  "migrated from #channel-name, originally opened `<date>`" note), even though
  the source channel-based ticket never had one. This is deliberate: it keeps
  every ticket in the unified collection structurally identical going forward,
  so the console never needs to special-case "does this ticket have a staff
  thread."

## 4. Cloning mechanics

**Verified against the pinned stack (`hikari==2.3.5` docs, `docs.hikari-py.dev/en/2.3.5`):**
`RESTClient.execute_webhook` accepts `thread` (post into a specific thread off
a webhook created on the parent channel), `username`, and `avatar_url` —
all three needed for this design, and all three exist on this version. Unlike
the modal-select gap found during console review, this is not blocked by the
library. Nothing in this codebase currently calls `execute_webhook` (grep
confirmed) — this would be new, not a reuse of an existing pattern.

Per source message, in order:

1. Read the original message (author display name, avatar, content,
   attachments, timestamp).
2. **Strip real `@mentions`/pings** before reposting — the clone should not
   re-notify the original user or any staff member. Render mentions as plain
   text (e.g. `@OldUsername`) instead of a live mention.
3. Post via `execute_webhook` into the destination thread, `username`/
   `avatar_url` set from the original author, since one webhook can impersonate
   any name/avatar per call — no need for one webhook per historical user.
4. **Timestamps cannot be backdated.** Discord stamps every message with its
   actual post time; there's no API to set it to the original date. Print the
   original date/time as visible text in the cloned message instead (e.g.
   prefix each clone with `*(originally sent 2025-03-11 14:02 UTC)*`).

**Attachment risk — audit before running, not after:** Discord CDN attachment
URLs expire roughly 24h after the message was posted. Any attachment on a
message old enough that its CDN link has already expired is **permanently
unrecoverable** — the migration tool can't fetch what's gone. Recommend a
dry-run pass that reports which old messages still have live attachment URLs
vs. already-dead ones, before committing to a full backfill, so the scope of
unavoidable loss is known upfront rather than discovered mid-run.

## 5. Data layer — what actually needs to be in Mongo

Bot-to-bot content copying needs no Mongo relay — it reads from the source
channel and writes to the destination thread directly. But the console's
search only ever queries Mongo (see [ticket-data-model.md](ticket-data-model.md)),
so a backfilled ticket is invisible to search unless it has a document there.
Minimum fields, matching the shape search already filters on:

```
user_id, player_tag (or tag), username, thread_id (the new public thread —
the console's "location"), status, ticket_type
```

No message bodies, no attachment blobs — those live only in the cloned
Discord thread itself. This mirrors the flag-record pattern specified in
[ticket-console.md](ticket-console.md)'s Related section: small,
purpose-built collections per concern rather than one document trying to
hold everything.

## 6. Scale and the thread cap

~1,500 legacy tickets are expected. At 2 threads each (public + staff, per
§3), that's **~3,000 new threads** against Discord's undocumented but
observed-in-practice active-thread ceiling of roughly 1,000 per guild.
Running the backfill without archiving would hit that ceiling well before
finishing.

**Mitigation (decision #6): archive each thread pair immediately after
creation**, not at the end of a batch. Archived threads don't count against
the active-thread limit. This makes the ceiling a non-issue regardless of how
many of the 1,500 eventually get backfilled — and unlike the live-ticket
case, it's mandatory here rather than a preference.

> **Why this is settled here but open in the console doc.**
> [ticket-console.md](ticket-console.md) §7 flags auto-archiving of *live*
> resolved tickets as recommended-but-unconfirmed, because there the
> alternative (never archive anything) is genuinely available. For the
> backfill it isn't: 3,000 threads against a ~1,000 ceiling fails outright.
> So archiving is forced for migrated tickets regardless of how §7 is
> eventually settled for live ones. If §7 lands on "never archive," these
> two rules coexist fine — migrated tickets are archived on creation, live
> ones never are — but §7 must not be read as overriding this section.

This also connects to the rate-limit incident on record —
[incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md)
— as a reason not to blast through all 1,500 quickly even if the thread cap
weren't a factor: this bot has already hit an unexplained channel-write rate
limit once in production. One-at-a-time, operator-paced execution (decision
#5) is the mitigation for both risks at once.

## 7. What the pilot needs to prove before scaling

Per decision #7, before running the rest of the ~1,500:

- A backfilled, immediately-archived thread pair is still **found by console
  search** (this should just work — search hits Mongo, not Discord, and
  archived threads aren't deleted).
- A backfilled thread **can still be opened on demand** from a search result's
  jump link. Archived threads reject some interactions until unarchived, so
  the console's jump-to-thread path likely needs to auto-unarchive
  (`PATCH` the thread) before or as part of the jump. **Unconfirmed — this is
  exactly what the pilot is for.**

If either fails on the pilot tickets, that's a stop-and-fix point before
touching the other ~1,498.

## 8. Open items — not resolved here

- Which server is "the" target server, and bot presence/permissions in every
  source server being consolidated from — an operational decision, not a
  technical one, left to whoever runs the backfill.
- Whether the backfill is a slash command, a script, or both — not specified.
- Old-channel deletion timing (immediately after a successful backfill, or
  held until all 1,500 are done) — user's plan is to verify the pilot first;
  no deletion policy has been decided beyond that.

## Related

- [ticket-console.md](ticket-console.md) — the search surface backfilled
  tickets become visible in.
- [thread-ticketing-proposal.md](thread-ticketing-proposal.md) §3.5 — the
  separate Mongo-only migration for this server's own 361 existing documents.
- [ticket-data-model.md](ticket-data-model.md) — the `tickets` collection
  shape the lookup record (§5) is built to match.
- [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md)
  — prior production rate-limit incident informing the "go slow" decision.
