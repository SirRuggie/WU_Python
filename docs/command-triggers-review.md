# Command triggers redesign — development review

Prompt 31, branch `codex/command-triggers-2`. Not released.

## Permission QUESTION (report only)

`server_management.allowed` calls `dashboard_allowed` without the write flag for
browser actors. The current grant catalog has management scopes, including
`text_commands`; it has no view-only grant for this editor. The same explicitly
granted management scope consequently allows both reads and writes. The separate
`strikes_read` aggregation is a read route convenience; strike mutation routes
still request their distinct strike scopes. The legacy scope expansion and session
scope intersection remain in place. A hypothetical future view-only grant could
not be enforced by this branch without extending the policy; no permission behavior
was changed here. Should a separate view-only permission model be designed in a
follow-up? The characterization test records the current behavior; this is source
analysis, not a production write probe.

## Copy changes

- Text commands → Command triggers (documentation)
- Type a trigger like !trigger in Discord to post its saved reply → Type a command like !rules in Discord. The bot posts its reply.
- Enabled in Discord → On
- Message text (outside embed) → Text above the card
- Mentions & recipients → Pings
- Allow pings in message and embed → Ping the people and roles in this reply
- Mention a user or role with the trigger → Let members add @person or @role
- Anyone can use enabled commands. Replies appear in the same channel. → The reply appears in the same channel.
- Separator → Line; Media gallery → Image gallery; Text + accessory → Text with small image
- Message card → Card; Action buttons → Buttons; Dropdown → Menu
- Formatting guide → Formatting help; Appearance → Look; Delete command disclosure → Danger zone
- Change history → History

## Removed recipient path

Repository search found no caller of `text_command_recipients.start()`. Only its
old `cr:` dispatch handler and picker-specific tests referred to the module. Removed
that unused path and corrected the guide. Inline recipient payload/validation and
send-before-delete regression tests remain; no live Discord notification was sent.

## Verification

- Network-isolated backend: 5,030 passed, 21 skipped, 162 subtests; scope/permission
  additions separately passed (17 tests). `/tmp/wu-trigger-full-backend.log`.
- Frontend: 1,062 passed / 203 files with two workers; type check and build passed.
  `/tmp/wu-trigger-full-frontend-final.log`, `/tmp/wu-trigger-build-final.log`.
- Five mutations killed in a separate export: native confirm, out-of-channel reply,
  cooldown before lookup, deletion missing history, swallowed error missing outcome.
  `.local/trigger-mutation-results.json` and corresponding per-mutation logs.
- Isolated fake-data browser: 320/360/390/1440px, no overflow or console errors,
  visible 44px targets and minimum 12px text. Command input `v` pattern rejects a
  space and accepts a hyphen. List usage, editor sections, Danger zone, searchable
  channel picker and history screenshots in `.local/trigger-browser-evidence/`.
  At 360px the editor region is 1,559px / 1.95 screens; the audit reported 5.4
  screens before this change (not a new baseline measurement).
- Complete build and layout gate passed (core dashboard, clan weights, strikes, and
  replacements). `/tmp/wu-trigger-full-layout.log`. The strike fixture deliberately
  exercises unavailable tracking responses; the gate completed with exit 0.

The first frontend full run used the wrong working directory for relative fixture
reads; rerun correctly. A concurrent full run had one quick-selection timeout;
all tests passed with two workers. New test harness fixes included the correct
Hikari exception class, reading HTTP exception text, selecting Remove rather than
Clear, and opening the local test session before browser checks. The browser
inspection led to limiting the keyboard hint to desktop widths as well as a fine
pointer. No production or Discord messages were sent.

Outcome metadata is best effort and revision-guarded: a database failure or an edit
while a reply is in flight can leave the usage display behind. It never causes a
reply retry or changes a successful delivery into a send failure. Unknown delivery
failures remain a single attempt. History only marks saved after the guarded
mutation succeeds; failed CAS entries remain explicitly unconfirmed.

Claude review165 required corrections: PATCH and old history snapshots now keep
current channel/role restrictions when those keys are absent; explicit empty lists
still clear them. Thread messages may use an allowed cached parent channel. Command
navigation uses the in-app discard guard, including Back replay and Keep editing;
delete history offers only the before snapshot. Focused backend69 passed; frontend
1064 passed; TypeScript/build passed. Removing omitted-scope preservation produced
two assertion failures in old-tab and old-history tests. Full backend regression
is being rerun before release. No production messages were sent for these checks.

## command-triggers-2 — 2026-10-30

Released tag `command-triggers-2`, revision
`5d09708b8cdc6ac0349a20c75293bd8eae9153fc` (PR93). Frontend, backend and bot
were activated together. Scope omission now preserves existing channel/role
restrictions for old tabs and old history; explicit empty lists clear them.
Cached thread parents satisfy channel scope. Navigation uses the in-app discard
confirmation, and delete history has no unsupported Restore action.

Integrated verification: 5111 backend passed, 21 skipped, 162 subtests; 1111
frontend passed; TypeScript/build and 320/360/390/1440 isolated browser checks
passed. The omitted-scope mutation failed both old-tab and old-history regressions.
Earlier full layout and five runtime mutations passed. No live command was invoked.

The SQLite backup SHA-256 is
`98ce0c991417e22f9f94a754e2e12dcb6a828c78113f3a47025a955fe98cfb2d`.
Mongo command/config/clan/history archives were read back and verified. All
protected SQLite hashes and counts matched before and after activation; all three
command definitions matched, excluding normal usage/outcome runtime fields.
Evidence: `.local/command-triggers-release-evidence/`, including backup manifests,
activation, postcheck and service journals. Readiness and runtime imports passed;
bot PID3928340 and dashboard PID3928433 started from the release revision.

Public entry `index-DBoE0wgU.js` SHA-256
`d079b7fa7a53cf298c9828ba578f8dfd44dd85430bc8c8350b2235bca2b4c10c`
and affected asset hashes matched the immutable release. Anonymous command access
returned401; no new service errors were found.

Claude handoff169: production smoke PASSED read-only at360px. Three enabled
commands, channel/role scope lists, Delete the trigger message and Saved state
were visible; no overflow, 4xx/5xx, tracebacks or IdentityLockBusy. Nothing saved
or sent. Actual live command delivery remains untested; Ruggie may check it.

Rollback code target for frontend/backend/bot:
`5f8fb1427e488bc69a1f67eb82f4e97615af621b`. Retain immutable assets and use
`.local/command-triggers-release-evidence/activate.py rollback` only while the
current revision matches its guard. Never restore production data for code rollback.
PR attachment UI failed with an MCP error; GitHub merge/release evidence is intact.
