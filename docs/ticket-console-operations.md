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

1. Prepare distinct Main and FWA candidate/staff parent text channels and their
   recruiter roles. Deny public access to staff parents. Give the bot and
   recruiter role the permissions reported by command validation. Legacy
   cloning additionally requires the bot to manage webhooks and attach files in
   both destination parents.
2. Bind and validate each type. The bot owner, who must also be an Administrator
   in the intended target guild, must run the first command that establishes the
   global target binding:

   ```text
   /ticket configure-threads type:Main candidate-parent:<channel> staff-parent:<channel> recruiter-role:<role>
   /ticket configure-threads type:FWA candidate-parent:<channel> staff-parent:<channel> recruiter-role:<role>
   /ticket thread-config
   ```

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
   `View Channel` to `@everyone`:

   ```text
   /ticket console channel:<private recruiter channel>
   ```

   Verify the returned message link, chart, open-ticket picker, and Find action.
   The console cannot be moved to another channel by re-running the command.
8. In the intended intake channel, run `/ticket setup` once. Each run posts a
   new entry panel, so do not repeat it unless another panel is wanted.

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
