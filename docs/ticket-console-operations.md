# Thread ticket console operations

This is the operator source of truth for the implemented ticket runtime. It
supersedes unresolved operational notes in the [console design](ticket-console.md),
[thread proposal](thread-ticketing-proposal.md), and
[legacy migration design](legacy-ticket-migration.md).

## Runtime contract

- Use one configured target guild and one shared, private recruiter console.
- Store only `open`, `approved`, or `denied`; the console labels `open` as
  **New / open**.
- Create one private candidate thread and one recruiter staff thread per ticket.
- Allow a new ticket after approval or denial, but only one open ticket per
  applicant and type.
- Approve or deny from the console; do not claim, release, close, or reopen.
- Keep terminal and migrated thread pairs locked and archived. Console links
  open them read-only without unarchiving them.

## Configure and activate

Run every command in the intended target guild as an Administrator.

**Pre-deployment resolution gate:** while the current legacy deployment still
owns channel tickets, approve or deny every open legacy channel ticket. Do this
before activating the thread feature; do not carry an open channel ticket into
the new runtime. Both dry-run and confirmed `/ticket migrate-store` refuse to
continue while any legacy channel ticket remains `open`.

1. Prepare at least two parent text channels: one candidate parent and one
   staff parent. Main and FWA may use the same candidate parent and may use the
   same staff parent; four parent channels are optional, not required. A
   candidate parent and a staff parent must always be different channels. Deny
   public access to every staff parent. Give the bot and recruiter role the
   permissions reported by command validation. Legacy cloning additionally
   requires the bot to manage webhooks and attach files in both destination
   parents.
2. Bind and validate each type. The bot owner, who must also be an Administrator
   in the intended target guild, must run the first command that establishes the
   global target binding:

   ```text
   /ticket configure-threads type:Main candidate-parent:<channel> staff-parent:<channel> recruiter-role:<role>
   /ticket configure-threads type:FWA candidate-parent:<channel> staff-parent:<channel> recruiter-role:<role>
   /ticket thread-config
   ```

   Reusing the same candidate-parent selection for both commands and the same
   staff-parent selection for both commands is valid. Each command rejects a
   pair whose candidate and staff selections are the same channel.

   After the first save, any Administrator in the bound target guild may
   configure the other type or repair its settings. A different target guild is
   rejected.
3. Take a database snapshot before the confirmed storage transition.
4. Preflight the canonical store:

   ```text
   /ticket migrate-store confirm:false
   ```

   Require zero open legacy channel tickets, understood live source counts, and
   no unique-index conflicts; the destination can be empty before the copy. If
   a `closed` row is reported, determine its real outcome from source evidence,
   then repeat the dry run with both fields:

   ```text
   /ticket migrate-store confirm:false closed-ticket-id:<exact ID> closed-status:<Approved|Denied>
   ```

   Never guess or bulk-map `closed`.
5. Repeat the passing command with `confirm:true`. Require verified counts and
   no reported divergence. This idempotently upserts the canonical collection,
   installs indexes, audits any explicit classification, verifies the copy, and
   activates canonical storage. It never deletes `button_store`.
   Do not set `ticket_store` manually.
6. Re-run `/ticket thread-config`, then inspect `/ticket config`.
7. Configure the one console in a recruiter text channel that denies
   `View Channel` to `@everyone`. A separate private console channel is
   recommended so the persistent hub is not mixed into either thread parent:

   ```text
   /ticket console channel:<private recruiter channel>
   ```

   Verify the returned message link, chart, open-ticket picker, and Find action.
   The console cannot be moved to another channel by re-running the command. If
   the saved channel was deleted, `/ticket console` reports its exact saved ID
   as missing and refuses relocation. Record that ID and repair the saved
   binding through the approved maintenance path before retrying; do not try to
   create a second console elsewhere. If the channel still exists but is
   inaccessible, restore the bot's access and retry in the bound channel.
8. In the intended intake channel, run `/ticket setup` once. Each run posts a
   new entry panel, so do not repeat it unless another panel is wanted.

## Daily recruiter workflow

### Understand account identity

- When a ticket opens, the bot force-refreshes every Clash account linked to the
  applicant's Discord ID. The candidate panel can show that the first check is
  pending. Until the first success or failure is persisted, the staff account
  and Chocolate panels may be absent. After that first result, staff copy
  distinguishes a failed lookup from a successful result with zero accounts. A
  failed lookup never means that the applicant has no accounts; it is durable
  retry work.
- **Currently linked** means the latest successful link-service snapshot. It
  drives the account count and the automatic FWA Chocolate checklist.
- **Permanently recorded** or **observed** tags are the append-only identity
  history: tags disclosed in candidate messages, including questionnaire
  answers, plus every linked tag seen in any successful snapshot. Search,
  prior-ticket matching, and flags use this history. A tag remains attached to
  the ticket after the applicant unlinks it, but it no longer appears in the
  current-account Chocolate checklist.
- Approve and deny both force-refresh the complete linked-account list again
  immediately before attempting the decision.

### Review FWA Chocolate and manage flags

- Every FWA staff thread receives automatic, staff-only Chocolate checklist
  pages with one link for each currently linked account. The bot updates those
  pages when the current snapshot changes and retires pages that are no longer
  needed. Pending, failed, and confirmed-zero link states are labeled
  separately.
- Open each Chocolate link and read the site yourself. The bot provides links
  only; it does not fetch, infer, or record a Chocolate blacklist verdict.
- In the console, open the ticket detail and choose **Manage flags**. This is
  the primary way to add or update **Blacklisted**, **Previously denied**, or
  **Not loyal to WU**, and to remove an active flag with a permanent removal
  reason. A change binds the applicant's Discord ID and every recorded player
  tag. Only **Blacklisted** blocks approval; the other two are cautions.
- Use the recruiter-only slash commands only as a fallback when the ticket
  detail flow is unavailable:

  ```text
  /ticket flags identity:<Discord ID or #player tag>
  /ticket flag-add kind:<flag> reason:<reason> discord-ids:<IDs> player-tags:<tags>
  /ticket flag-remove flag-id:<exact ID> reason:<reason>
  ```

  `flag-add` needs at least one Discord ID or player tag. Copy an exact flag ID
  from the ticket detail or `/ticket flags` before using `flag-remove`.

### Approve or deny

1. Open a ticket from the shared console and read its staff account context,
   matching flags, earlier-ticket links, and, for FWA, every current-account
   Chocolate link.
2. Choose **Approve** or **Deny** in the private ticket detail. The bot performs
   the final linked-account refresh before it writes the decision.
3. Approval remains blocked and the ticket stays open when the final lookup
   fails, when zero Clash accounts are currently linked, or when an active
   blacklist flag matches the Discord ID or any recorded player tag. Restore
   the account service, complete linking, or resolve the verified flag as
   appropriate, then reopen the latest ticket detail and try again.
4. If an FWA approval refresh finds a newly linked account, approval stays open
   and the bot refreshes the staff Chocolate checklist. Review the refreshed
   links, then choose **Approve** again. If checklist delivery is still pending,
   the bot says so and keeps retrying; wait for the update and try again. A
   later refresh that finds another new account repeats the same review gate.
5. Denial is allowed even when the final linked-account lookup fails or returns
   zero accounts. A lookup failure is stored with the denial and retried
   automatically, so a later successful snapshot can still update the durable
   staff context and FWA Chocolate pages.
6. After either decision is recorded, applicant notification, staff context,
   thread archiving, and console refresh are durable follow-up work. A yellow
   **Decision recorded; updates retrying** result means the decision is safe;
   wait for recovery and ask an administrator to inspect only if it persists.
   The terminal candidate and staff threads remain locked, archived, and
   available read-only from the console.

## Legacy pilot: one ticket at a time

Select one to five terminal source tickets. The operator must be an
Administrator in the target and owner or Administrator in the source; the bot
must be able to read both source histories. For each ticket:

1. Run a read-only preview. Choose the configured destination parents for the
   inferred ticket type.

   ```text
   /ticket migrate-legacy source-guild:<server> source-channel:<ticket channel> target-guild:<configured server> candidate-parent:<channel> staff-parent:<channel> type:Auto status:Auto confirm:false
   ```

   Select `source-staff-thread` when auto-detection is ambiguous. An explicit
   `type` or terminal `status` is an authoritative correction: it replaces
   the corresponding stored or inferred value. It cannot make a source proven
   `open` or `new` eligible. Use `user-id` or `username` only when identity
   cannot be inferred safely. A non-empty `player-tags` override replaces all
   stored and applicant-authored tag inference; it does not add to it.
2. Confirm only when the preview shows the correct terminal outcome, ticket
   type, applicant, histories, tags, and attachment audit. If the preview reports
   attachment risk, accept it only by copying that preview's exact `LOSS-...`
   value into `attachment-ack` on the confirmed rerun. Omit `attachment-ack`
   when the preview reports no risk. An open source ticket must be approved or
   denied first.
3. Re-run the exact selections with `confirm:true`. The command creates or
   resumes one destination pair, clones candidate and recruiter history, records
   a canonical ticket, then locks and archives both threads.
4. Verify before selecting the next source:

   - Compare message order, visible original timestamps, staff history, and
     attachments or loss notes.
   - Confirm both destination threads are locked and archived.
   - Find the ticket by Discord ID and username with `/ticket find`; also use a
     player tag when one is present.
   - Open both console links while they remain archived.
   - Confirm the source channel and source staff thread are unchanged.

Stop after the selected one-to-five-ticket pilot. Only after every selected
migration is complete and verified, unlock further migrations with:

```text
/ticket approve-migration-pilot confirm:true
```

## Resume and recovery

### Live ticket workflows

- A committed ticket keeps its canonical row and thread pair if opening setup
  delivery is interrupted. Startup recovery resumes the same pair and retries
  its setup messages without creating duplicates.
- Pending or failed linked-account snapshots, staff applicant context,
  automatic FWA Chocolate pages, applicant decision notices, terminal archive
  convergence, and persistent-console refreshes retry automatically. These
  workflows use durable state and message markers across process restarts.
- Preserve both ticket threads, bot-authored marker messages, and ticket
  automation-state rows while recovery is pending. Do not delete and recreate
  them to force a retry.
- Recovery may temporarily make a terminal thread writable so the bot can add
  or repair its own pending message. It then relocks and rearchives the thread;
  this does not reopen the ticket status.

### Legacy migration

- Re-run the same `/ticket migrate-legacy` selections with `confirm:true`, or
  allow startup recovery to resume an already-confirmed item.
- Resume uses independent candidate/staff `last_source_message_id` checkpoints
  and durable per-message markers. The source guild/channel identity, thread
  pair, ticket number, and canonical record are reused; duplicate pairs,
  messages, records, and IDs are rejected or reconciled.
- Keep migration state, destination threads, and message markers intact. Do not
  change destination selections for an existing source identity.
- Interrupted destination threads are locked and archived until recovery can
  safely continue.

## Write and rollback boundaries

| Operation | Writes | Recovery boundary |
|---|---|---|
| `migrate-store confirm:false` | None | Correct the reported data and repeat. |
| `migrate-store confirm:true` | Canonical rows/indexes/config; the explicitly classified `button_store` row | Before activation, keep partial upserts and repeat the same idempotent command. After activation and new thread writes, recover forward; this release has no legacy-channel runtime fallback. |
| `migrate-legacy confirm:false` | No Discord or Mongo writes; attachment URLs are read | Correct selections/metadata and repeat. |
| `migrate-legacy confirm:true` | Destination threads/messages, migration checkpoints, canonical ticket | Do not delete partial artifacts. Repeat the same command or let startup recovery resume. |

Legacy Discord sources are strictly read-only: the migration fetches source
guild, channel, private staff thread, messages, roles, and attachments, but
never edits, archives, renames, or deletes them. Temporary webhooks and all
thread edits exist only in the destination. There is no source cleanup tool.
