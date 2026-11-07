# Moderation history and log settings

## Scope and design

Extend the existing member archive with confirmed kicks and bans, and let staff
configure each event's Discord destination. History stays the landing view; Log
settings is a separate focused view. Preserve `/server/member-activity` as an alias
for `/server/moderation` and retain the existing API and saved records.

Default join/leave posting remains channel `1004519991648997447`. New kick/ban
posting starts off until staff selects a destination. Disabled Discord posting
does not remove archived history. Text channels use compact Components V2 cards;
forum channels use a compact embed starter, the documented forum-message shape,
with one searchable post per event. Do not attempt a second notification format
after an ambiguous create response.

Use green Join, red Leave, amber Kick and stronger red Ban labels. Color supports
explicit action text. Keep the saved profile/avatar, join date and relative event
time. Reason and moderator information are included only when known; dashboard
secondary details expand without cluttering the history list. Discord profile
links can become unavailable after deletion; saved identity remains readable.

## Primary references

Reviewed October 26, 2026:
- https://docs.discord.com/developers/resources/audit-log
- https://docs.discord.com/developers/events/gateway-events
- https://docs.discord.com/developers/resources/channel#start-thread-in-forum-or-media-channel

Member removal alone does not prove a kick or ban. Confirm kicks from an audit
entry and bans from their dedicated event. An audit reason or actor must be tied
to the correct action and target. The bot already requests GUILD_MEMBERS and
GUILD_MODERATION. Read-only production checks confirmed audit-log access (200),
channel inventory (200), and six forum channels. No moderation action was taken.

The final validation, deployment evidence and remaining limitations will be
recorded after implementation review.

## Validation

- Sol backend implementation and independent Sol adversarial review; Luna UI.
  Review fixed missed-unban/reban recovery and prevented nearby audit facts from
  replacing an explicitly identified ban's moderator or reason.
- Affected backend/transport suite: 91 tests and 62 subtests passed. Transport
  tests cover text V2, forum multipart starter/avatar/tag receipts, inert mentions,
  and no second POST after an ambiguous error. These are not live delivery tests.
- Full frontend suite: 92 files / 396 tests passed; TypeScript and isolated Vite
  build passed. Required war-reminder validation passed.
- Restricted real Mongo test collection verified CAS settings, concurrent event
  dedupe/claim, uncertain no replay, pagination/search, saved avatar and size bound;
  temporary test collection cleaned afterward.
- Isolated browser checked desktop, 390px and 320px layouts, ban filtering,
  channel search and forum required tags, successful save with reduced response,
  conflict preserving edits, unavailable channel inventory preserving settings,
  and forbidden responses clearing settings. No horizontal overflow at narrow
  widths. Synthetic external markup rendered as text. Browser automation stalled
  on the existing unsaved-navigation confirmation, so that cancellation path is
  not claimed as browser-verified; the existing shared navigation guard is used.

## Limits and operational behavior

A removal and its confirmed kick/ban are separate records; a leave does not
assert voluntary departure. Late audit enrichment updates history but an already
posted card may omit late reason/actor information. Missing gateway events cannot
be guaranteed to backfill. Unknown join dates remain unknown; moderation cards
label older saved dates as last known. No actual moderation actions or test posts
were performed in production, and forum delivery still needs observation after
staff configures a forum and a real event occurs. Existing history is retained;
no signup/roster schema or data migration is involved.

## Release verification

Deployed implementation `92f12117b21c6099cfd1513910f165e55952de65` to both
checkouts. Bot runtime imports passed and member-events extension loaded in the
new process with no current-process error markers. Bot and web services active.
Public `/server/moderation` HTML and entry/moderation assets match the reviewed
isolated build; signed-out history and settings requests return 401. Older hashed
assets were retained during atomic index installation.

Private pre-release SQLite backup retained locally. Post-release digests match
for 93 signups, 93 roster entries, one publication and one season. Live log settings
retain the existing join/leave channel; kick/ban posting remains disabled. Archive
indexes have no expiry. No data migration or live notification test occurred.


## Forum post destinations — October 27, 2026

Moderation settings now include accessible active forum posts in channel search.
Pasting an unlisted numeric ID offers an explicit Look up action; the staff-only
read endpoint checks the post and its parent forum before selecting it. Saved
archived posts are resolved during reload. Save and delivery recheck server
ownership and inherited permissions, including Send Messages in Threads.
Locked posts and private/non-forum threads are excluded. Unlocked archived posts
can receive replies; Discord automatically unarchives them on send (see
[Discord thread documentation](https://github.com/discord/discord-api-docs/blob/main/developers/topics/threads.mdx)).
Selecting a forum channel still creates new posts; selecting a post sends replies.
No storage migration, automatic retry, mention policy, or receipt changes.

Validation: 34 backend tests plus 7 subtests across member events, moderation
settings and transport; 6 focused frontend tests; TypeScript and isolated Vite
build passed. Backend regressions cover parent ownership, staff visibility,
missing thread-send permissions, locked posts, private threads, malformed IDs,
lookup authorization, save revalidation, and reply transport. Existing tests
cover stale settings revisions, cancellation, duplicate events, and uncertain
send receipts. Isolated browser fixtures verified name search, keyboard Enter
selection, ID lookup, and explicit Save. Desktop and 320/390px mobile inspections
checked readable controls, visible focus, results, and no horizontal overflow.
These checks do not establish live Discord delivery or full screen-reader support.
No production settings, live messages, or served dashboard assets were changed.

## Layered routing and log cards — released October 30, 2026

Released as `moderation-logs-1`, PR #68, `c494022e924994435496c3e4f0722eb781460380`.
The bot shipped first and passed startup/gateway readiness before the backend and
frontend were exposed. Claude ACCEPT 95 and read-only smoke 98 passed. Effective
Join/Leave remained enabled at channel 1564485264364011580; Kick/Ban remained
disabled with no channel; every forum tag stayed null. Raw settings and revision 1
were unchanged, with no normalization writes. See [release evidence and guarded
rollback](dashboard-backend-releases.md#moderation-logs-1--october-30-2026).
No production Send test was used. This verifies the read-only dashboard/runtime,
not live Discord delivery. Avatar reads returned 503 for three of eight requests
in smoke; cards fell back to initials. Prompt 33 item 6 tracks the follow-up.

The four supported events remain Join, Leave, Kick, and Ban. Settings schema 2
adds one main destination, Members and Moderation category destinations, and an
optional destination for each event. An event uses its own destination when set,
otherwise its category destination, otherwise Main. Turning a category Off stops
its Discord posts even when an event has an override; disabling one event stops
only that event's posts. History capture and its name/ID, type, date filters and
expandable Details stay available when posting is off. Kick and ban history cards
show the known moderator and reason inline. Unavailable actor, reason, role,
join-date, account-date, and member-count data remain visibly unknown or use the
specific fallback text; they are not inferred from unrelated actions. Existing
default Join/Leave posting remains unchanged.

Legacy settings are normalized **on read**, with their four event destinations
preserved as event overrides, Main unset, categories inheriting Main, and the
revision preserved. A read does not rewrite Mongo. Only an explicit Save changes
persists schema 2 through the existing revision compare-and-swap check. A dry-run
against a backup copy contained 22 rows and one settings row; all four effective
enabled/destination values and the revision matched before and after
normalization, unrelated rows were untouched, and the dry-run made zero writes.
This early 22-row result is backup-copy evidence, not a live migration. Claude's
later review used a 24-row backup. The release-time archive held 25 member-event
rows; its exact raw settings and all four effective destinations passed pre/post
checks. These are successive snapshots, not contradictory migration counts.

The bot and dashboard preview share the same card builders. Text-channel messages
and replies to existing forum posts use Components V2: an event accent, avatar
thumbnail/name, event title and details, separator, member-count/ID/time footer,
and one Discord profile link button. `allowed_mentions` suppresses pings. A new
forum post retains the compact embed starter and link button because Discord's
forum thread-create payload does not accept the Components V2 flag; its preview
uses that same forum starter payload. External identity, role, and reason text is
escaped. Receipt, duplicate-claim, and uncertain-delivery behavior still permit
only one send attempt; no second format or automatic retry follows an ambiguous
Discord response. These checks use simulated transport and do not establish live
Discord rendering or delivery.

The explicit **Send test** action uses saved settings only. The dashboard disables
it for an unsaved draft and confirms the saved effective destination before one
POST with the event and revision. The backend rechecks staff write access, CSRF,
revision, destination ownership and posting permissions, then reserves an atomic
per-event 10-second rate slot. Rate and audit records live in the separate
`settings.member_event_test_audit` collection; sample sends never enter member
history or delivery receipts. A known superseded revision is rejected before
the Discord POST. If Discord acceptance or audit completion is uncertain, the UI
asks staff to check Discord before trying again and never retries automatically.
A save in the narrow interval after the final revision read and before the POST
could still send a sample to the previously confirmed destination; there is no
cross-service transaction covering Mongo and Discord.

Historical accepted revision `91c94c3` passed **4,863 backend / 923 frontend**
tests. Those counts describe that reviewed revision, not the later integrated
release.

Final integrated verification passed 4,863 backend tests, 21 skipped and 162
subtests, plus 933 frontend tests, TypeScript/build. Clean final-tag frontend
checks passed again; the tag differed only in three documentation files from
the integrated checked tree. Four required feature mutants and seventeen mocked
release-gate checks passed. Earlier focused development counts are superseded by
these full integrated results.
Release backups, protected-state comparisons, public hashes and runtime checks
are recorded in the linked release record. Current-invocation journals were
clean; the old bot's shutdown CancelledError was excluded from new-process
readiness. No real Discord Send test has been performed by this release workflow.


## Moderation polish follow-up

History resolves unique moderator IDs through the existing Discord member adapter,
with at most three concurrent requests and a three-second page budget. Names are
cached per application and guild for 120 seconds (unknown results for 30 seconds),
with a 256-entry bound. Unknown members remain visibly unknown; IDs are hover
metadata. Sample previews render member names while retaining the real Discord
payload used for delivery. Category toggles remember the last active destination
mode in the current editor session. A fresh page with a saved Off category starts
with Main because no prior mode is stored in the existing schema.

A revision recheck that cancels a test before posting releases only its own rate
claim. Sent and uncertain attempts retain the ten-second slot. The cancelled audit
record remains. Older rate records need no migration; their existing expiry works.

Avatar diagnosis: this endpoint reads archived Mongo bytes; it does not fetch a
Discord avatar. Confirmed missing/empty/unsupported images now return 204 and are
negatively cached for 30 seconds, bounded to 128 guild/event keys per application.
Every request still checks current staff authorization before using the cache.
Mongo and authorization outages remain genuine 503 responses. A simulated Mongo
server-selection failure reproduces the actual helper's 503 conversion. This
identifies a possible failure path, **not the proven cause of the three historical
production 503s**; no production tracing or requests were performed for this
follow-up. The client uses its existing initials fallback on an empty image.

## Avatar concurrency follow-up (prompt 36, review pending)

The dashboard now owns one lazy Mongo client per application and closes it at
application cleanup. Injected fixture clients remain externally owned. Each
request still performs authorization, including negative avatar-cache hits;
permissions and image bytes are not cached. The missing-avatar cache still holds
only confirmed absence, and database outages remain uncached 503 responses.
Underlying HTTP failure causes are recorded as exception class names only, never
connection strings or exception messages. Failed images retain initials with no
automatic retry (therefore no retry storm).

An isolated 12-request fixture reproduces the old per-request-pool fan-out under
a constrained connection budget. All requests succeed with the shared pool;
restoring the old client allocation kills the concurrency test. This demonstrates
the allocation defect, not proof that Mongo rather than Discord caused the three
historical production failures: those logs discarded the underlying cause. The
new exception-class diagnostics are needed to confirm any remaining live failure.
No live API load test or Discord delivery is claimed.

Legacy member-activity URLs canonicalize to Moderation and retain its existing
permission gate. A category or row with no effective destination says “Not
posting — no channel set”; stored enabled flags, routing and save payloads are
unchanged. Tests cover the message alongside checked switches and no settings
writes.

UI validation uses `tests/avatar-polish.browser.cjs <fixture-port>` against the
isolated moderation fixture. It follows the legacy URL through the local test
session, verifies the canonical Moderation URL at 360×800 and 1440×1000, supplies
an empty-channel settings response without saving it, and checks for overflow
and browser errors. The category switch wraps its status at narrow widths.


### Moderation history identity read cache

Only GET history and GET event avatar share Discord identity results for 30 seconds,
keyed by signed-in user, bounded to 128 LRU entries. Concurrent reads share one
in-flight fetch; failures are not cached. A cancelled reader does not cancel the
shared fetch; logout removes the user's entry, including an in-flight one.
Authorization and current dashboard grants are checked for every request. Discord
role/ownership changes can take up to 30 seconds to affect these two read endpoints.
Every write and all other endpoints obtain fresh Discord identity. Mongo pooling,
confirmed-missing-avatar caching and zero automatic image retries remain unchanged.
The historical production 503 cause is still an inference, not proven.

## Moderation polish release closure — 2026-10-30

`moderation-polish-1`, PR #72, shipped frontend and isolated dashboard backend at
`568d5689e94909d9123461ca7f0524144eca3f50`. The bot stayed at
`1a4aae32eb5581162190fbc0954b9536bbc9187c` without a restart. Claude passed the
read-only 360px smoke (handoff 108): history names, Log settings and saved status,
with no saves or test sends. Public entry `index-BNw8xs6y.js`, SHA-256
`ea437b05560fc1ad0f7e4024cb7a9fdea995227da8011a8e5fe253d1ed191e64`, and all 36
checked owning/shared assets matched the manifest.

Final integrated checks: 4,916 backend tests, 21 skipped, 162 subtests; 963 frontend
tests; TypeScript/build. Sixty scratch release checks passed, including a mutation
that removes the final runtime check. Backup:
`.local/moderation-polish-1-backup-20261030T152118Z`. SQLite protected rows, 12 Mongo
collection counts, raw moderation settings and effective destinations matched.
Active strikes remained 3,607 with zero clears or unexplained changes. Backend
cwd, two consecutive public config 200s and the final current-invocation journal
passed after data reconciliation. The historical frontend/backend rollback was
`1a4aae32eb5581162190fbc0954b9536bbc9187c`, with the bot unchanged; later releases
supersede that target. Evidence remains in `/tmp/wu-moderation-polish-release/`
(`live.json`, `mongo-postcheck.json`, `strike-comparison.json`).

Smoke also found three transient avatar 503s among 11 first-load requests;
19 individual refetches later returned 200. Initials remained usable. Historical
logs recorded no underlying exception class, so the cause is not proven. Prompt
36 tracks concurrency, class-only diagnostics and two display follow-ups; this
release closure does not claim those 503s are fixed or that real Discord test
messages were sent.

## Avatar 503 release — October 30

`avatar-503-1` is live at `44a37083f8fa5cb19df79873b9f6a412cceccd21`.
The dashboard frontend and backend use immutable release directories for that
revision; the bot stayed at `fb46bd388af287ea30f6296407853ff40105e39b`
without a restart. Public `index-DtTrE87U.js` SHA-256 is
`d22d3ac2c274700968a641dfe2047b7310646585c81cac692561230130dfeed4`.

Integrated checks passed: 5,002 backend tests (21 skipped, 162 subtests), 1,043
frontend tests, TypeScript and build. Isolated 360px/1440px checks covered avatar
loading, legacy redirect, denied access and disabled test sending without a
channel. Activation required two consecutive public config 200 responses, active
service with the expected cwd, public asset hashes, anonymous denials and a clean
current journal.

The private backup is retained at `.local/avatar-503-1-backup-20261030T211645Z`;
SQLite SHA-256 `4d781f50bf0d75e85929a0ceeca9f9241c72f85295e2d0bbd3414e669e1b2158`.
Pre/post protected counts and digests matched: 155 signups, four publications,
seven saved lineups, 3,558 active strikes. All twelve checked Mongo collection
counts and moderation settings matched. No database restore or live message was
performed. Previous frontend/backend assets at `fb46bd3` remain available for
code-only rollback; the guarded local coordinator is `/tmp/wu-avatar-release/run.py`.

Claude's read-only production smoke passed: runtime and public hash matched,
`/server/member-activity` redirected to `/server/moderation`, and 22 of 22 parallel
no-store avatar reads returned 200. No backend 503 or traceback appeared in the
checked journal; nothing was saved or sent. Deployment tooling needed a recursive
manifest finalizer for nested shared assets; this was a staging-tool issue, not an
application or production check failure.


## Four new logs (2026-11-06)

Seven event keys join the existing four in the same settings document (schema stays 2,
revision-checked PUT). All default to off with no destination.

| key | category | source |
|---|---|---|
| `timeout_add`, `timeout_remove` | moderation | audit-log `MEMBER_UPDATE` entry whose `communication_disabled_until` change sets a future time, or clears it |
| `member_update` | members | `MemberUpdateEvent` diff: nickname, username, display name, avatar, server avatar, discriminator (only when not `0`) |
| `link` | messages | `GuildMessageCreateEvent` with at least one `http(s)://` URL |
| `invite_create`, `invite_delete` | invites | `InviteCreateEvent`, `InviteDeleteEvent` |
| `invite_use` | invites | `MemberCreateEvent` plus a diff of invite use counts |

Categories are now `members`, `moderation`, `messages`, `invites`. Reading an old row fills the
missing keys from defaults; nothing is written until a revision-checked save.

New settings fields: `ignores` (`channel_ids`, `role_ids`, max 100 ids each, 17 to 20 digits;
link event only) and `invite_names` (`{code: name}`, max 200). `GET /api/cwl/manage/member-events/invites`
reads the bot's snapshot from the `member_invites` collection (one document per guild and code).

The settings GET also returns `roles` (id, name, color, position, managed; `null` when unreadable) and `roles_available` (boolean). The dashboard treats roles as available only when the flag is `true` and `roles` is a list; otherwise saved ignored roles show as "Unknown role" and adding is disabled.

How each part works:

- Timeouts post from the audit entry and dedupe on the audit entry id. Moderator, reason,
  duration and expiry come from it.
- `member_update` needs the cached previous member, so it is skipped when that is missing.
  Username, display-name and avatar changes arrive on `MemberUpdateEvent` because Discord sends
  the updated user object in `GUILD_MEMBER_UPDATE`. The nickname actor is read from a single
  audit-log page; when no entry matches the actor is omitted.
- `link` skips bot and webhook authors, ignored channels, threads whose parent channel is
  ignored, and authors with an ignored role. It dedupes on the message id.
- `invite_use` snapshots invites at start and after every join, under one lock so two joins do
  not share a diff. An invite is named only when exactly one explains the join: one use count
  rose by 1, the vanity count rose, or an invite one use short of its limit vanished. Anything
  else, and any fetch or permission failure, shows "Unknown invite".
- `link` and `invite_*` rows are written only while their log is on and are excluded from
  history search. Timeout and `member_update` rows are kept even when delivery is off.
- No avatar bytes are downloaded or stored for the new kinds; cards use the Discord CDN URL.

Limits:

- A timeout that runs out by itself is not logged; Discord writes no audit entry for it.
- Invite uses are joins, not link clicks. Attribution can be Unknown, and a join that races an
  invite delete can also read Unknown.
- The `GUILD_INVITES` intent (added in `main.py`) and the Manage Server permission are needed
  for invite create, delete and use counts. Without Manage Server every invite use is Unknown.
- The bot needs a restart to load the intent and listeners. Deploy the frontend with the backend:
  the settings PUT now requires every event, the four categories, `ignores` and `invite_names`.
- Link and invite rows are not pruned. There is no retention job. (Superseded by batch 2 below.)

## Moderation batch 2 (2026-11-06)

Bot-side decisions from contract v2. The timeline, member history and health endpoints and the
dashboard screens are owned by the API and UI work.

Event keys and categories:

- Categories, in order: `members`, `moderation`, `roles`, `messages`, `channels`, `server`,
  `invites`. New categories default to mode `main`; every new event defaults to disabled with no
  channel. An old settings row reads with defaults filled and saves as before.
- 21 new kinds: `unban`; `role_create`, `role_update`, `role_delete`, `roles_added`,
  `roles_removed`; `message_delete`, `message_edit`, `message_bulk_delete`; `channel_create`,
  `channel_update`, `channel_delete`, `channel_permissions`, `thread_delete`, `thread_lock`;
  `server_update`, `emoji`, `sticker`, `app`, `webhook`, `automod`. `emoji` to `automod` are one
  switch each and the card states added, changed or removed.

How each part works:

- Roles, channels, threads, server and unban post from the audit entry and dedupe on the entry
  id (`roles_added` and `roles_removed` add the kind, because one entry can carry both).
- A change made by an app account is skipped. The actor is an app when the cache says so, else
  one REST lookup is cached in the process; an unknown actor counts as human. Adding an app
  (`BOT_ADD`, `INTEGRATION_CREATE`) always posts.
- `role_update` and `channel_update` are skipped when only the position changed (position is
  never shown). `thread_lock` posts only when a person set locked or archived; auto-archive has
  no audit entry and thread creation is never posted.
- `unban` comes from `BanDeleteEvent` and audit `MEMBER_BAN_REMOVE`, in either order. Both use
  the ban episode as the dedupe key. The gateway-first row waits one second for the audit entry
  to add moderator and reason; an unban made by an app is dropped.
- `message_delete` and `message_edit` need the cached message. Bots and webhooks are skipped, and
  the existing ignore lists (channels, thread parents, roles) apply to `link`, delete, edit and
  bulk delete. Edit posts only when the text changed. Attachments show name and type only.
- Audit facts for message deletes are consumed once: Discord's entry `count` is a running total, so
  only the increase since the last seen count (per entry id) can attribute new deletes.
- One "App added" card per application: `BOT_ADD` and `INTEGRATION_CREATE` within 60 seconds pair
  by application id, or when an id is missing and only one entry of the other type is waiting.
- `message_bulk_delete` posts the count, channel, moderator when found, and a `.txt` transcript
  of the cached human messages (200 KB cap) as an attachment. A text channel references it with
  a file component; a forum starter attaches it. The transcript is kept on the row, so a post
  that is retried after a restart still has it.
- Join cards add account age ("New account" under 7 days), "Nth join" from earlier join rows
  (shown from the second), and "via name or code" when invite attribution finishes within 3
  seconds. The join waits on a per-user future set by the invite-use path; other joins are not
  held. Leave cards add time in server and drop the roles line when the cached member is gone.
- Cards for member kinds carry a "Member history" link button to
  `/server/moderation/member/<user id>` through `utils/dashboard_urls.py`; no dashboard base
  means no button.
- `HISTORY_TYPES` is join, leave, kick, ban, unban, timeout_add, timeout_remove, member_update,
  roles_added, roles_removed, invite_use. Of these, history kinds are kept when delivery is off.
- Retention: new rows get `expires_at` (30 days for link and the three message kinds, 90 days
  for the three invite kinds); other kinds have no field. A TTL index (`expireAfterSeconds` 0)
  on `expires_at` removes them. Settings, snapshot and invite documents never get one.
- `main.py` raises the hikari message cache to 10,000 messages; other cache defaults are kept.

Limits:

- A message that is not in the cache is never logged, and a bulk delete of uncached messages
  posts the count with no transcript. The cache is lost on restart and holds the newest 10,000
  messages, so older deletes and edits are missed.
- The delete moderator is best effort. It comes from a recent audit `MESSAGE_DELETE` entry for
  the same author and channel seen on the gateway in the last few seconds; Discord merges
  repeated deletes into one entry, so a later delete in a run can read no moderator.
- Changes made by apps are skipped, which includes this bot's own role changes.
- A rejoin count reads earlier join rows, so it starts at the first join the log recorded.
- Retention is by the Mongo TTL index only; it runs about once a minute and removes rows
  shortly after `expires_at`.

## Hardening (2026-11-06)

Four changes on top of batch 2, then a rework of audit replay. Code: `extensions/events/member_events.py`,
`utils/member_events.py`, `utils/member_event_settings.py`, `utils/member_event_cards.py`,
`cwl_web/member_events.py`.

- **Ignored bots replace "skip all bots".** Audit-sourced logs (roles, channels, server, app
  changes, member roles, unban) skip an actor only when its id is in settings
  `ignored_bot_ids` (17 to 20 digit ids, at most 50). A row that never saved the field ignores
  this bot's own id, resolved at runtime (`bot.get_me()`, else REST); if that id cannot be read,
  nobody is ignored. Once saved, the list is used as is, so staff may remove the own bot or
  save an empty list. Reading never writes; a PUT without the field (older clients) leaves it
  untouched. "App added" always posts. Message kinds still skip bot and webhook authors.
  Every bot seen as an audit actor is stored in one document
  `member-events-bot-actors:<GUILD_ID>` (`bots: {id: {name, last_seen}}`, newest 100 kept, a
  repeat within an hour is not rewritten). Settings GET adds response-only `bot_actors`
  (`id`, `name`, `last_seen`, sorted by name) from that document plus this bot, and always
  returns the resolved `ignored_bot_ids`; when this bot's id cannot be read and the row never
  saved a list, `ignored_bot_ids` is omitted (the dashboard shows "Bot list unavailable.").
- **Recovery after downtime.** The newest handled audit entry id is kept in
  `member-events-audit-cursor:<GUILD_ID>` (`last_audit_num` as an integer, `last_audit_id` as text, `updated_at`), only moving forward
  by one filtered update.
  After the startup invite snapshot a background task reads the audit log (newest first, 24
  hours and 500 entries at most), then replays missed entries oldest first through the same
  handlers. A replayed entry whose audit id is already on a stored row (`audit_entry_id` or
  an `...:audit:<id>` key) is skipped before its handler runs, so it never posts or changes ban
  state; unban rows record their audit id for this. A second "App added" for the same
  application id within 10 minutes is skipped even after a restart. Replayed cards carry
  "Recovered after restart". With no cursor (first run) it only sets the cursor. Live entries
  that arrive before recovery has read the cursor are held back from the cursor until it ends.
  A failure (for example 403 without View Audit Log) logs one warning and never delays
  startup. That gap stays unrecovered: the hold is released, so live entries move the cursor
  again and the next start does not retry it. Both documents have no `expires_at` and no
  `event_type`, so history queries never return them.
- **Card size limits.** Roles 10, permission changes 15, profile and setting changes 10,
  URLs 10, attachments 10, each followed by "+N more". A final guard keeps a Components V2 card
  within 3,800 characters of text, and a forum starter description within 4,000 (fields 1,000,
  total 5,800), cutting the longest lines first (never below 40 characters, never inside an
  escape) and then dropping trailing fields; "+N more" always equals the hidden items.
- **Public-channel health check.** Settings health adds an error `public_<channel id>` ("<name>
  is visible to everyone") for any enabled log destination, or the parent channel of a thread,
  that `@everyone` can view (View Channel or Administrator after channel overwrites).

Limits:

- Gateway-only events (message delete and edit, joins and leaves, invite create and delete) are
  not recovered. Audit `MESSAGE_DELETE` entries are skipped in recovery.
- Recovery uses hikari's `before` paging (newest first); hikari 2.6 has no `after` parameter.
  Past 500 missed entries, or beyond 24 hours, the older ones are not replayed.
- The ignore list is read at replay time, not when the entry was made.
- The bot-actor document is read and rewritten whole, so two near-simultaneous first sightings
  can drop one name until that bot acts again.
- A recovered kick or ban waits the same 1 to 2 seconds as a live one, so a long backlog posts
  slowly.
