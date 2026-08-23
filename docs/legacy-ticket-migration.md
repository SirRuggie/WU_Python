# Legacy ticket migration — terminal cloning into threads

**Status: implemented as `/ticket-pilot migrate-legacy`.** For the executable
operator sequence, use the
[ticket console operations guide](ticket-console-operations.md#clone-terminal-legacy-tickets).

## What the command does

The command previews or clones exactly one terminal, channel-based legacy
ticket into the configured thread-v2 destination. Confirmation creates or
resumes a private candidate thread, a staff thread beneath the private
recruiter-only parent, and a full terminal ticket row in `tickets`.

This is not a bulk store conversion:

- Legacy channel tickets remain authoritative in `button_store`.
- Thread-v2 tickets and completed clones are authoritative in `tickets`.
- The source Mongo row and every source Discord object remain unchanged.
- There is no source cleanup or deletion step.

Cloning is available only while rollout is in `pilot`, `thread_default`, or
`thread_only`. Sources proven `open` or `new` must first be resolved in the
legacy runtime. Other sources must preview as `approved` or `denied`; a stored
`closed` value requires an explicit per-ticket outcome.

## Access and destination guards

The operator must:

- Run the command in the configured destination guild as an Administrator.
- Own or be an Administrator in the source guild.
- Select the configured candidate and staff parents for the resolved Main or
  FWA type.
- Give the bot source-history access and the destination permissions validated
  by the command, including webhook and attachment permissions.

The candidate and staff parents must be different. Main and FWA may use the
same candidate parent and the same staff parent.

## Preview before every confirmation

```text
/ticket-pilot migrate-legacy source-guild:<server> source-channel:<ticket channel> target-guild:<destination server> candidate-parent:<channel> staff-parent:<channel> type:Auto status:Auto confirm:false
```

The preview makes no Discord or Mongo writes. It reports the inferred ticket
type, terminal outcome, applicant, candidate and staff message counts, observed
player tags, and attachment audit.

Optional reviewed corrections are:

- `source-staff-thread:<thread>` when staff-history detection is ambiguous.
- `type:Main` or `type:FWA` when type detection is wrong.
- `status:Approved` or `status:Denied` when the terminal outcome needs an
  explicit correction. A stored `closed` value requires this per-ticket
  classification.
- `user-id:<ID>` or `username:<name>` when applicant identity cannot be safely
  inferred.
- `player-tags:<comma-separated tags>` to replace, not extend, inferred tags.

An explicit outcome cannot make a source proven `open` or `new` eligible.

### Attachment loss acknowledgement

The command reads live source attachments when possible. If any attachment
audit result is not `live`—including unknown, not-audited, or incomplete audit
coverage—the preview returns an exact `LOSS-...` token. Confirm only after
reviewing the listed risk, and add `attachment-ack:<exact token>` to that
confirmed rerun. Omit the option only when every attachment audit is live. A
stale or mismatched token is rejected.

## Confirmed clone behavior

Repeat the previewed selections with `confirm:true`. The implementation:

1. Revalidates source identity, outcome, parents, permissions, and attachment
   acknowledgement.
2. Creates or resumes the same destination candidate/staff thread pair.
3. Clones candidate history and the detected or selected recruiter-only staff
   history. If no staff history exists, it records that fact in a
   destination-only note.
4. Reposts historical authors by webhook without real pings. Discord messages
   cannot be backdated, so the original timestamp is rendered visibly.
5. Writes the full terminal thread-v2 ticket record and durable migration
   checkpoints.
6. Locks and archives both destination threads.

No message bodies or attachment blobs are stored in Mongo. They remain Discord
content; Mongo holds the destination ticket, identity, location, status, and
recovery state needed by the console.

## Resumability and source safety

Confirmed cloning is resumable. Candidate and staff histories have independent
`last_source_message_id` checkpoints, and copied messages have durable markers.
Re-running the same confirmed source, or startup recovery, reuses the same
thread pair, ticket number, and ticket row rather than duplicating them.

Keep partial destination threads, migration rows, and bot-authored marker
messages while recovery is pending. Do not change destination selections for an
existing source identity.

Source access is strictly read-only. The implementation may fetch the source
guild, channel, selected staff thread, messages, roles, and attachments, but it
never edits, renames, locks, archives, or deletes them. All webhooks and thread
mutations belong to the destination. The source `button_store` row is not
modified or replaced.

## One-to-five-ticket pilot gate

Select between one and five terminal sources. Confirm and verify each one
before selecting the next. Further new selections remain blocked until all
selected migrations are complete and an Administrator runs:

```text
/ticket-pilot approve-migration-pilot confirm:true
```

Pilot approval fails unless there are 1–5 selected migrations and every one is
complete. A preview does not consume a pilot selection; a confirmed source does.

For every selected clone, verify:

- The terminal outcome, type, applicant, and observed tags.
- Candidate and staff message order and visible original timestamps.
- Attachments or explicit loss notes.
- Both destination threads are locked and archived.
- `/ticket-pilot find` locates the clone by Discord ID, username, and a player
  tag when present.
- Both console jump links open the archived threads read-only; they are not
  automatically unarchived.
- The source channel, source staff thread, messages, and legacy row are
  unchanged.

## Scale boundary

Each legacy ticket produces two destination threads. Immediate lock and archive
keeps terminal clones out of the active-thread population. Operator-paced,
single-ticket execution also limits Discord write pressure and makes attachment
loss and identity corrections reviewable before each confirmed copy.

## Related

- [ticket-console-operations.md](ticket-console-operations.md) — current setup,
  rollout, daily operation, and clone commands.
- [ticket-console.md](ticket-console.md) — the search and read-only thread
  surfaces completed clones use.
- [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md)
  — prior production rate-limit incident informing operator-paced execution.
