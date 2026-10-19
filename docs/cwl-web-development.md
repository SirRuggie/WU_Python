# CWL web application development

This application is being developed separately from the live Discord bot and
from the sample mockup at https://cwl.ruggie.zone/. The confirmed product
requirements are in [the CWL plan](cwl-web-dashboard-plan.md).

## Boundaries

- `cwl_web/`: Python HTTP API, Discord identity, read-only player data adapters,
  authorization, and isolated durable development storage.
- `web/cwl/`: React and TypeScript interface with the WU goldenrod design.
- The initial SQLite store holds development signups and settings. Family clans
  are read from the bot MongoDB clan directory; no bot collections are modified.
- The browser never receives provider credentials. It cannot grant itself staff
  access, declare its account links, or bypass season rules.
- An account may register for one pool per season. Different linked accounts
  belonging to the same member can register for Main and Lazy CWL respectively.
  A confirmed move replaces the existing pool atomically while signups are open;
  the request names the expected source pool so stale confirmations cannot move
  an account from an unexpected pool.
- Both pools accept linked accounts from any clan. Staff see a family-membership
  notation based on the signup-time clan and the bot directory; directory outages
  produce an unknown status rather than blocking signup. FWA, Tactical, Flexible
  Fun, and legacy Competitive are family categories; hosting-only categories are
  excluded. Manage family records through the existing bot.

## Live integration prerequisites

The workspace has existing player/link adapter configuration, but web OAuth
configuration was not found. The production bot's private environment was not
inspected or changed. Configure Discord OAuth through the application owner's
Developer Portal and the web service's private environment; never put credentials
in frontend variables, Git, or chat.

Discord sign-in must use a registered callback matching the development or
production website URL. Its authorization code is exchanged server-side; browser-
bound state protects the callback. See [Discord OAuth documentation](https://docs.discord.com/developers/topics/oauth2).

Keep development fixtures explicit and localhost-only. A fixture session does
not verify Discord sign-in or live player-data connectivity. Test both before
opening registration to members.

## Moving the application later

Keep the browser talking to a same-origin API. Moving hosts then requires moving
application code and durable data, provisioning server secrets, changing the
configured public origin and Discord callback, and updating DNS. A domain
change should not change member IDs, player tags, season IDs, or signup records.
The public mockup's browser-local state is not production signup data.

## Before a live season

Verify real Discord authentication, current owner and guild membership checks,
link ownership, family annotations, signup closure, concurrent cross-pool writes,
access revocation, and recovery from provider outages. Add operational backups,
rate limits, monitoring, and a deliberate shared storage integration before
connecting staff publication to the production bot. No automatic Discord
announcements are sent by this foundation.


## Run the local development preview

From `web/cwl`, run `npm ci`, `npm test`, and `npm run build`.
From the repository root, run:

```bash
CWL_WEB_DEV_FIXTURE=1 \
CWL_WEB_DB_PATH=/tmp/wu-cwl-dev.sqlite \
CWL_WEB_STATIC_DIR=web/cwl/dist \
.venv/bin/python -m cwl_web
```

Open http://127.0.0.1:8767/ and use the local test-session button. All sample
accounts and the development owner session are fictional fixtures. The database
persists between restarts at the selected path; `/tmp` is disposable. Choose a
private durable development path when retaining test data matters. Do not expose
fixture mode through a tunnel or public proxy.

Backend checks: `.venv/bin/python -m pytest -q tests/test_cwl_web_foundation.py`.

## Live configuration names

- `CWL_WEB_DB_PATH`: separate web database path, never the production bot DB.
- `CWL_WEB_STATIC_DIR`: built frontend assets (`web/cwl/dist`).
- `CWL_WEB_HOST`, `CWL_WEB_PORT`: default loopback and port 8767.
- `CWL_DISCORD_CLIENT_ID`, `CWL_DISCORD_CLIENT_SECRET`: Discord application OAuth credentials.
- `CWL_DISCORD_REDIRECT_URI`: registered HTTPS callback ending in `/api/cwl/auth/callback`.
- `CLASHKING_API_TOKEN`, `COC_API_TOKEN`: read-only link and game-data providers.
- `MONGODB_URI`, optional `MONGODB_ROUTES`: bot clan directory connection and
  existing namespace routing. The web adapter performs reads only; provision a
  read-only database credential for deployment.
- `CWL_WEB_DEV_FIXTURE`: must be absent or `0` for real authentication.

Provide configuration through the web process environment. The launcher does
not load the bot's `.env` automatically. Live cookies require HTTPS. Owner and
guild membership information obtained during Discord login is bounded by the
short session lifetime; stricter real-time revocation remains a production task.


## Verification — 2026-10-14

- 18 isolated backend tests passed, including cross-pool concurrency, member
  privacy, permission revocation, CSRF, expiring one-time OAuth state, provider
  ownership checks, outage handling, and Mongo family-directory filtering.
- Five frontend selection tests passed; TypeScript/Vite production build passed.
  Runtime dependency audit reported no vulnerabilities.
- Browser-tested fixture login, selecting two Lazy accounts, Apply to all,
  review/submit, persistence after backend restart, a different Main account,
  cross-pool selection blocking, staff signup pools, and adding a hosting clan
  to the season lineup.
- Measured no document overflow at 390px, then fixed and rechecked 320px member
  and staff views. Closed mobile navigation no longer exposes offscreen controls.
- Independently called the real read-only family adapter using workspace private
  configuration: source `bot_mongo`, status `ok`, 15 family clans. No records
  were modified. The browser development session still uses fictional fixtures.
- Live Discord sign-in is not configured or end-to-end verified. Account/game
  provider behavior is covered with tests; real member signup remains gated on
  OAuth setup. Roster assignment, publication, bonuses, production persistence
  integration, backups, and live deployment are subsequent work.


## OAuth deployment — 2026-10-14

The public URL https://cwl.ruggie.zone/ now serves the authenticated web
foundation. The existing `wu-cwl-demo-web.service` user unit runs the repository
Python environment on loopback port 8766 with a private Git-ignored environment
file at `.local/cwl-web.env`. No credential values belong in this document.
Live web data is separate at `.local/cwl-web-data/cwl.sqlite` with owner-only
filesystem permissions. Fixture mode is disabled publicly. The original mockup
HTML remains intact at the previously documented visualization path; its former
service configuration is saved as `.local/cwl-web-data/preview-service.rollback`.

Verified HTTPS 200, unauthenticated identity API 401, public fixture login 404,
and a Discord OAuth 302 with the correct client ID, callback, and identify/guilds
scopes. The state cookie has Secure, HttpOnly, and SameSite=Lax flags. The browser
reached Discord authorization; successful user consent and token exchange still
require completing sign-in. The local fixture preview remains separate on 8767.


## Discord profile header

New OAuth sessions retain Discord global display name (falling back to username)
and a Discord CDN avatar URL. The header displays a circular picture and name;
failed images fall back to an initial. Session schema migration adds nullable
profile columns without deleting existing sessions or signups. Older sessions
continue working with username fallback; signing in again populates the profile.
No additional OAuth scopes or access-token persistence are needed.


## Staff roster and real FWA source — 2026-10-14

Staff Roster builder now uses durable season roster entries and hosting rules.
Manual weight edits use thousands in the interface (174.5 means 174500); backend
values are total integer weights. Manual assignments accept any season hosting
clan regardless of signup pool; signup pool remains unchanged. Capacity is enforced.
Auto-placement previews only unassigned, unkept accounts using configured pool,
capacity and weight ranges, and the Lazy lower-league answer. Applying verifies
the revision and recomputes the preview within a transaction. Relevant member
and staff changes invalidate stale previews. Assigned member withdrawals/pool
moves require staff to unassign first; hosting clans with assignments cannot
be removed. Roster edits have actor/time audit records.

FWA weights are fetched from https://www.fwastats.com/Weights.json (public JSON),
validated and cached for 15 minutes. Refresh FWA weights in the staff workspace
to populate or update source values; overrides survive refresh. Source updated
time is distinct from fetch time. Missing or unavailable source values remain
visible and manual edits remain available. No bot MongoDB writes are involved.
The preserved pre-migration backup is `.local/cwl-web-data/before-roster.sqlite`.
This adds staff draft placements; publishing assignments and Discord announcements
remain separate work.

Validation: 37 focused backend tests and 10 frontend tests passed. Browser QA
covered configuring rules, fixture source refresh, preview/apply, Main signup
assigned manually to a Lazy hosting clan, manual weight override preserving
placement, and mobile layout. Live read-only FWA adapter verified with Four and
Twenty player tags. Service restart and current public bundle verified.

Active directory clans now appear directly in roster destinations; the duplicate
season-lineup UI is removed. Existing archived assignments remain visible but
archived clans cannot receive new placements. Bulk assignments validate and
commit atomically; unconfigured manual hosts default to 50 slots, while explicit
limits apply. Added numeric TH/weight sorts and visible-filter bulk selection.
43 backend + 11 frontend tests passed. Browser verified directory-only bulk
assignment, sorting and mobile layout. Live November roster sees 4 active hosts.


## Published rosters and member assignments — 2026-10-14

Implemented staff Publish roster preview and explicit publication. Each publish
saves an immutable numbered snapshot of account identity, signup pool, hosting
clan identity, weight provenance/overrides, and joining instructions. Partial
rosters require explicit acknowledgement; empty rosters cannot be published.
Draft changes remain private until another publication. Publishing checks the
reviewed revision, advances it to prevent competing staff overwrites, records
an audit event, and handles exact retries without duplicating a version.

My assignments is directly available to members. Its authenticated endpoint
returns only the signed-in user's accounts from the latest published snapshot,
with hosting clan links, instructions, version/time, and Awaiting placement
states. It exposes neither other users' accounts nor staff weight/actor data.
Withdrawals and later roster edits do not rewrite published snapshots.
Archived seasons remain readable but cannot be published again.

Database migration is additive. Private pre-migration SQLite backup:
`.local/cwl-web-data/before-publication.sqlite`. No real roster was published
as part of deployment. Discord announcement delivery remains future work.
Validation: 46 backend and 13 frontend tests passed; isolated browser fixture
confirmed staff publication followed by member assignment/instruction display,
including a 390px mobile layout. Existing aiohttp test warnings remain.


## Immediate member placements and Discord announcements — 2026-10-14

User superseded publication-gated member visibility: My assignments now reads
current saved signup/placement rows for the authenticated user only, immediately
after staff assignment. Placements are labeled provisional when unpublished or
changed since the official version. Publishing still preserves immutable history;
withdrawals no longer appear in the current member view, but remain in snapshots.
No staff weights or other members' accounts are exposed.

Publish roster includes separate per-season Main and Lazy Discord channel
selectors, validated against the Warriors United guild text/announcement channels.
Staff explicitly save destinations and send previews; publication never sends.
Announcements use the published pool counts and dashboard link, without pings or
private player lists. Each version/pool/channel has a durable delivery receipt.
Exact duplicate sends return the saved receipt; concurrent sends reserve once.
Definitive rejections can be retried explicitly, while uncertain or in-progress
attempts block blind resend. A stranded uncertain delivery requires operator
review before further action; there is no automatic resend or reconciliation UI.

Dashboard environment now includes the existing bot DISCORD_TOKEN and
CWL_WEB_PUBLIC_URL privately. The bot account's readable environment was used
with explicit user authorization; no credential values were printed. Read-only
live Discord lookup succeeded. No real Discord messages were sent during rollout.
Backup: `.local/cwl-web-data/before-announcements.sqlite`.
Validation: 52 backend and 16 frontend tests pass; isolated browser fake-transport
flow verified channel save, explicit send receipt, and duplicate-send disabled UI.
Discord request fields checked against the official Message Resource:
https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx


## Clan comparison, atomic swaps, and placement Undo — 2026-10-14

Roster builder now compares two active hosting clans side by side, with current
occupancy, average known Town Hall/weight, and numeric TH/weight sorting. Staff
select one account per clan, review both moves, and swap atomically, including
when both clans are at capacity. Cross-pool moves remain staff-only and preserve
signup pool. Manual swap placements are kept. Mobile A/B switches retain both
selections; changing clans, season, or roster revision clears stale selections.

One-step Undo is server-backed for single placement/keep changes, bulk assignment,
automatic placement, and swaps. It belongs to the acting staff member and the
exact resulting roster revision. Later roster edits or publication invalidate it.
Undo restores only assigned clan and keep status, preserving weight provenance,
manual weights, and immutable publication snapshots. Final destination capacities
and active clans are checked transactionally; Undo is consumed once, without redo.

Validation: 58 CWL backend tests and 18 frontend tests passed. Browser fixture
verified a swap between two full 15-account clans and Undo restoration, plus
390px mobile side switching with both selections retained. No live placements
were changed for testing. Pre-migration private database backup:
`.local/cwl-web-data/before-swap-undo.sqlite`.


## Searchable channels and Manage integration boundary — 2026-10-14

Discord destinations now use searchable comboboxes supporting partial name/ID,
click selection, arrow keys, Enter, Escape, and scrolling active results. Results
are capped at 30 with a narrow-search hint. Removed the separate joining
instructions input from publication and its member display. Legacy snapshot
instructions are retained for compatibility and are not silently erased; staff
instructions belong in the roster announcement.

Research confirmed `/manage` → CWL → Publish Final Roster is distinct from
CWL Return Pings. Its `_publish` handler in extensions/commands/cwl_dashboard.py
calls extensions/tasks/cwl_reminder.py `send_campaign_message` with message key
`roster`, cycle YYYY-MM, and Main/Lazy audiences. utils/cwl_campaign.py loads
saved template body, artwork, role IDs, channel and roster/guide buttons from
routed bot_config (normally settings.bot_config). Native delivery claims and
receipts are in that campaign and cwl_pending_reminders. Return-ping lists in
lazy_cwl_lists are not assignment publications.

The web SQLite announcement sender is NOT integrated with Manage. Shared channel
IDs alone do not share receipts or prevent duplicate sends between both systems.
A future bridge must use a bot-owned worker and the native ledger, then retire
the web direct send path; no live campaign settings/messages were changed here.
Required bridge details: explicit season-to-campaign month mapping (signup month
may precede CWL month), version-aware native occurrence identity and uncertain
send handling, a stable My assignments link surviving OAuth, preservation of
native artwork/roles/guide buttons, and deliberate authorization mapping between
web owner-granted editors and Manage administrators. These were researched,
not implemented in this UI update.

Validation: 20 frontend tests and production build passed. Browser fixture
verified partial channel-name search and Enter selection without sending.

### Shared Manage publishing — 2026-10-14

The dashboard now binds a web season explicitly to a native Manage campaign
month. Main/Lazy channel choices, announcement body, and primary roster link
save through the native campaign revision checks; other template fields,
artwork, role pings, and additional guide buttons remain intact. The dashboard
can use its My assignments deep link as the primary roster URL.

The running bot consumes reviewed web requests from separate bot_config queue
documents every ten seconds. Both interfaces use the existing campaign sender
and delivery ledger: one roster announcement per campaign month and pool.
Publishing another web snapshot does not reset that delivery receipt. Unknown
Discord outcomes block blind retries in both interfaces; definite failures and
stale requests require explicit review/retry. Native /manage remains supported.
CWL_WEB_MANAGE_BRIDGE=1 disables the superseded independent web send endpoints.

Deployment included native campaign/helper/reminder/dashboard files, web API,
and frontend. Production heartbeat and active services verified; no announcement
was sent. CWL backend regression suite passed 275 tests; frontend passed 24.
The broad repository run also found seven unrelated existing failures.
Before sending: select the matching Manage month in Publish roster, review each
pool's destination/template/link, save changes, then explicitly queue its send.

## Staff participation tracking — 2026-10-14

Deployed Results & participation staff navigation. Staff can manually record
nullable attacks (0–7), stars (0–21, at most three per known attack), and notes
against published accounts. Search, pool/clan filters, and numeric sorting are
available on mobile and desktop. Unsaved card edits survive filter changes;
season changes warn before discarding them. Saves show explicit confirmation.

Additive participation_records and participation_audit tables retain original
published account/clan identity, source publication, author, and timestamp.
Withdrawals and republishing do not erase saved results. Changed/removed roster
accounts are flagged; archived seasons are read-only. Both account revision and
publication version are checked to reject stale edits, including first-save
races. Participation does not advance placement revision or touch Manage.
No live war import or bonus eligibility/awards are implemented in this slice.

Validation: 281 CWL backend and 26 frontend tests passed. Isolated browser checks
verified saving/reloading, 390px mobile layout, and unsaved filter retention.
Public build index-Bnv-GxOP.js and additive schema verified after service restart;
no real participation records or announcements created. Private SQLite backup:
.local/cwl-web-data/before-participation.sqlite.

## Automatic CWL participation sync — 2026-10-14

Deployed explicit month selection, optional 15-minute collection, and staff
Sync now in Results & participation. Uses existing COC_API_TOKEN for read-only
league-group and league-war requests. Month defaults only from an explicit
Manage binding; labels are never parsed as dates. No production season was
configured automatically (there are no published live rosters yet).

Source observations and per-field manual overrides are separate. Existing
nonnull manual results migrate as overrides; notes-only saves do not freeze
source counts. Explicit Use synced results clears overrides with revision,
publication and source timestamp checks, retaining notes. UI refresh and saves
of other rows preserve dirty card inputs. Changing months clears old source
counts after warning about drafts.

The bounded worker uses lifecycle cancellation, skips disabled/archived seasons,
and deduplicates wars and clan sides. It retains finished-war evidence, accounts
for rotated/benched members from league-group rosters, excludes preparation from
recorded zero counts, and rejects mismatching months. Partial/missing/stale
observations are labeled and age on read. Saved identity survives withdrawal
and publication changes. Sync never changes native Manage campaigns or sends
Discord messages. New tables are additive; backup:
.local/cwl-web-data/before-participation-sync.sqlite.

Validation: 300 CWL backend tests plus 27 frontend tests passed. Tests cover
scheduler execution/shutdown, auth, archived seasons, month/config races,
missing/ended/preparation wars, deduplication, bench rotation, outages, manual
corrections, reset, and retention. Fixture browser checks verified imported
1 attack/3 stars alongside retained manual7/18, observed0/0 for a second player,
partial warnings, saved automatic toggle, and 390px mobile layout. A browser
confirmation-dialog tooling timeout prevented completing the reset interaction
in UI; reset behavior passed backend tests. Public build index-BauCCSdI.js and
all five sync tables verified after restart. Live Four and Twenty league-group
probe returned404, so no live results sample was available for end-to-end import.

API semantics checked against the official developer portal and maintained SDK
schema/source: https://developer.clashofclans.com/ and
https://clashofclans.js.org/docs/api/interfaces/APIClanWarMember . Actual API
inWar/warEnded values normalize to canonical WAR/ENDED; omitted attack arrays
for observed active/ended members mean no attacks, while preparation is pending.

## Compact member and staff layouts — 2026-10-14

My assignments groups accounts by hosting clan with compact account rows, one
clan link per group, assigned clans first, awaiting placement last. Publication
status remains visible in a short strip; details expand on demand. Long group
lists have clan jump links. Mobile header spacing brings account rows near the
top instead of requiring scrolling through repeated clan cards.

Seasons & clans defaults to Hosting clans with separate section menus for Season
settings, Family clans, and Signup pools. Family records are hidden until chosen.
Search, active/archive and pool filters, and eight-row pages bound list length.
Create-season controls expand on demand; current season selection stays visible.

Publish roster separates Review & publish from Discord announcement. The publish
control is above a searchable, collapsed clan-grouped preview; awaiting accounts
sort last. Main/Lazy announcement panels switch without dropping drafts. Bound
campaign-month editing and full message previews are collapsed. Existing API,
partial-roster acknowledgement, send confirmation, and Manage delivery logic are
unchanged. No production roster or message changed during this layout work.

Validation: TypeScript/Vite production build and29 frontend tests passed. Browser
fixture verified10 accounts across two clans plus awaiting placement, a25-clan
paginated family directory, separate publish steps, and390px mobile layout.
Public build index-BGYYrGm-.js verified. Frontend rollback copy:
.local/cwl-web-data/dist-before-compact-layout. No backend restart required.

## Bonus review and history — 2026-10-14

Deployed staff bonus rules, per-clan slots, season-wide draft selections, server-validated confirmation preview, and recorded selection history with reasoned voids. Rules are unset by default. Confirmation records a dashboard decision only; it does not award in game or send Discord messages. Prior spreadsheet history is not imported.

Confirmations snapshot reviewed participation and policy, enforce monthly duplicate/capacity checks across seasons, and reject stale previews. Archived seasons remain read-only. Incomplete source data or unknown policy requires a selection reason and warning acknowledgement.

Validation: 307 CWL backend tests and 32 frontend tests pass; compileall and diff whitespace checks pass. Browser fixture verified slots, draft, warning acknowledgement, confirmation, consumed capacity, duplicate prevention and history on desktop/mobile. Production database and previous dist backed up before rollout; public bundle index-CpOdDckJ.js verified. Both web and bot services active; no live bonus confirmations created during testing.

## Signup list visibility — 2026-10-14

Signed-up accounts in either pool are hidden by default. The Show signed-up accounts toggle restores normal preference and confirmed pool-move controls. Select-all and submitted selection only include visible accounts; toggling clears drafts to prevent hidden selections. Successful signup resets the toggle; editing a saved preference enables it. Member labels and API fallback wording now use Signed Up/signups. Validated with 32 frontend tests, TypeScript production build and browser fixture checks for hidden accounts, visible counts and restored move guidance. Deployed bundle index-SHFLgir7.js; previous static build backed up.

## Roster readiness — 2026-10-14

Publish review now summarizes unassigned accounts, missing effective weights and accounts in clans exceeding effective capacity. Each issue opens Roster builder with its matching filter; Return to publish review reloads the preview. Counts derive from the same draft accounts, including both pools. These are review aids; existing publication acknowledgement and server assignment capacity enforcement remain unchanged, as does /manage. Added focused filter/capacity tests; all 34 frontend tests and production build pass. Browser fixture verified clear checks, a new unassigned warning and direct filtered navigation. Deployed index-DBTMFhZ3.js with previous dist backed up.

## Discord login recovery — 2026-10-14

Authorization URL uses percent-encoded scope spaces and prompt=none to avoid repeated consent for existing grants. Explicit retry requests consent. Browser callback failures return to the CWL login screen with a fixed safe error and retry link; API clients retain JSON status errors. State verification remains mandatory and single-use. No claimed fix for the unreplicated Opera GX Discord-page loading problem. Foundation suite: 28 passed; TypeScript production build passed.

## Staff CSV exports — 2026-10-14

Added staff-only Export season page and GET /api/cwl/seasons/{season_id}/export.csv. Accounts export supports current saved placements or latest immutable published roster, including source/manual/effective weights, participation with separate recorded identity fields, and dashboard bonus status. Complete participation export retains records no longer in the latest publication. Bonus history includes confirmations and voids and explicitly distinguishes selections from in-game awards. Current and archived seasons are readable; export makes no data changes.

CSV uses UTF-8 BOM, correct quoting/newlines, formula escaping, text Discord IDs, unknown blank values and explicit source/override status. Read authorization is enforced on the server, responses are no-store, filenames use numeric season IDs.

Validation: 312 CWL backend tests and 34 frontend tests passed; TypeScript production build, compileall and diff checks passed. Browser fixture verified staff navigation, export choices and download feedback. Deployed bundle index-CJI4lFpr.js; previous dist backed up. No bot or Manage changes.

## Whole-season acceptance trial — 2026-10-14

Added an isolated API trial spanning Main/Lazy signup and confirmed moves, withdrawal, hosting rules, FWA weights, automatic placement, provisional member assignments, publication, per-member privacy, manual participation, bonus confirmation, all three exports, archive and blocked archived writes. Uses fixture providers and temporary SQLite only; no live announcements or roster changes.

Found and fixed an archive bug: global revision changes from archiving, closing signups or renaming a season wrongly marked unchanged published rosters provisional. Publication status now compares roster snapshot content when revisions differ. Genuine unpublished edits remain marked changed even after archive; optimistic concurrency revisions remain unchanged.

Validation: 314 CWL backend tests and 34 frontend tests passed; compileall and whitespace checks passed. Mobile 390x844 browser fixture verified signup review, completion and next actions, hiding saved accounts, Signed Up list with TH icons and red withdraw controls. Native Manage receipt/deduplication tests passed within the suite; no real Discord message was sent. The known buddy-specific Opera OAuth loading problem remains unreplicated; this trial does not certify external Discord/browser behavior or replace a real staff pilot.

## Automatic backup and recovery (2026-10-14)

Installed on the current host using **Restic 0.19.1**, the SQLite online backup
API, and official MongoDB Database Tools 100.19.0. Release checksums were verified.
No new backup file format, encryption, retention engine, or database dump engine
was invented. The small wrapper is `tools/backup/cwl_backup.py`.

- `cwl-backup.timer`: every 5 minutes; consistent SQLite snapshot, CWL private
  environment, user service definitions, source/build assets, and recovery config.
- `cwl-mongo-backup.timer`: every 15 minutes; all visible application databases,
  excluding Mongo internal `admin`, `local`, and `config` databases. Includes
  production `settings` and `database`; the bot stays online.
- `cwl-backup-check.timer`: daily at 04:17 host local time; reads all repository
  data, restores SQLite into scratch space, verifies integrity/foreign keys/hash/
  table counts, and restores Mongo into a fresh authenticated loopback server.
  Every BSON document, index definition and collection option is compared.
  Scratch data/server/credentials are removed after the check.
- Retention: all snapshots within 2 days, 48 hourly, 30 daily, 12 weekly, 12
  monthly recovery points. A verified restore precedes pruning; repository
  structure is checked again afterward. Separate tags preserve both data sets.
- Timers are enabled and `Persistent=true` catches missed schedules after boot.
  User lingering is enabled. The web, bot and Cloudflared services are enabled.
  Web startup additionally checks the mounted data volume and nonempty SQLite
  file; it retries instead of silently initializing a fresh database.

### Locations and off-site backup

The live app is on RAID1 `/nvme0n1-disk`; the encrypted local repository is
`/home/ruggie/.local/share/wu-backup/restic` on the **separate root disk**. The
root-owned `/backup` disk was not modified. Staging/status/private diagnostic
logs are in `/home/ruggie/.local/state/wu-backup` with owner-only access.

The encryption password is `/home/ruggie/.config/wu-backup/password`; a private
second copy is `.local/cwl-backup-recovery/password` on the application volume.
**Save this password in a separate password manager/off-machine recovery kit.**
An encrypted backup cannot be recovered without it, even if the files survive.
Never commit, print, or send it in chat.

The user created `wu-private-backups` and enabled object writes on 2026-10-14.
The encrypted Restic repository is initialized under that bucket's `restic/`
prefix. No backup data is stored in the public media bucket. Credentials remain
in the private, Git-ignored `.local/cwl-backup-r2.env` (permissions 0600), using
`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`; the account ID comes from `.env`.

Off-site copying is enabled by `~/.config/wu-backup/r2-enabled`. Every scheduled
backup copies retained snapshots to R2, catching up after outages and skipping
copies already present. The daily maintenance job verifies both repositories,
performs isolated restores from each, and applies retention. Initialization has
already completed; do not rerun `init-r2` against this existing repository.
There is no need for a separate AWS S3 account.

### Inspect and recover

```bash
systemctl --user list-timers 'cwl-*'
systemctl --user status cwl-backup.service cwl-mongo-backup.service cwl-backup-check.service
journalctl --user -u cwl-backup.service -u cwl-mongo-backup.service -u cwl-backup-check.service --since today
```

Jobs fail visibly in systemd on tool, integrity, restore, or remote upload errors.
Private status JSON retains timestamps of the last successes; inspect service
failure state too, since an old success does not establish current protection.
Discord backup notifications are configured below; no outside monitoring is configured.

For recovery, **restore to a fresh directory first**, never over the running
application. Point Restic at the local repository and password file:

```bash
export RESTIC_REPOSITORY=/home/ruggie/.local/share/wu-backup/restic
export RESTIC_PASSWORD_FILE=/home/ruggie/.config/wu-backup/password
/home/ruggie/.local/bin/restic snapshots
/home/ruggie/.local/bin/restic restore SNAPSHOT_ID --target /path/to/private-recovery-directory
```

Choose a `cwl` snapshot and a `mongo` snapshot as needed. Restic recreates the
saved absolute path tree under the target. The SQLite file is under
`home/ruggie/.local/state/wu-backup/cwl/`; Mongo dumps are under the adjacent
`mongo/dump/`. Verify before switching production: SQLite integrity/foreign keys
and saved manifest; Mongo restore via official `mongorestore --gzip
--stopOnError` into a **separate** database server. Reconcile the two snapshots
before restoring coupled web/Manage records. Stop writers during any actual
cutover. Keep the old data until the recovered application is validated.

Source/build and `cwl-web.env` are included for rebuilding the Python environment
and restoring services on a replacement host. The existing deployed bot checkout,
Atlas accounts/network/project configuration, R2 public media objects, and host
OS are not fully backed up by this CWL job. Do not treat it as a machine image.
Official Mongo binaries were obtained from the URLs/checksums retained in the
September Mongo recovery manifest; installed copies now live persistently in
`~/.local/opt/wu-backup-tools`, not `/tmp`.

### Recovery limits and verified evidence

No system guarantees zero loss. With successful jobs, the intended local
recovery windows are 5 minutes for CWL and 15 minutes for Mongo, plus job runtime.
Failed jobs, downtime or loss of this machine can widen that window. Mongo is an
online logical dump, **not** a cross-collection or cross-database point-in-time
snapshot; no Atlas continuous-backup configuration was changed. SQLite and Mongo
snapshots are not one atomic transaction. For a migration/final cutover, quiesce
writers and reconcile both stores. Off-site copies and an off-machine key are
required to survive loss of the whole host.

Initial checks: three SQLite backup safety tests passed; full encrypted
repository read and isolated SQLite restore passed; authenticated Mongo restore
matched 55 collections and 8,999 documents plus indexes/options. Systemd units
validated; backup services ran successfully under systemd; guarded web restart
succeeded and the public site returned HTTP 200. No full host reboot was
performed, and no production database was restored or overwritten.

Credential follow-up: the first supplied key was described as valid for one
week. It was replaced with a different key; the replacement's expiry is not
verified. Confirm its expiry in Cloudflare and replace before expiration.
Save the Restic password in an off-machine password manager/recovery kit too;
R2 credentials alone cannot decrypt the backup. Backup-failure notifications are now configured below.

R2 activation verified at 2026-10-14 22:33 UTC: both scheduled backup services
uploaded successfully; the daily maintenance service completed with exit 0.
Full local and remote repository checks and isolated SQLite/Mongo restores
passed. The R2 Mongo restore matched 55 collections and 8,999 documents, including
index and collection-option comparisons. All three timers remain enabled.


### Backup failure and recovery notifications (2026-10-14)

`cwl-backup-monitor.timer` runs every two minutes with persistent scheduling.
It reuses systemd job results/timer states and existing backup status files; it
uses the existing bot identity through Discord REST, without another gateway
session or bot restart. Destination selected by the owner:
`947166650321494067` (`「🤖」bot-testing`), stored in private
`.local/cwl-backup-alerts.env`. The destination was validated against the WU
server and a clearly labeled setup message was delivered successfully.

Failure signals: missing/failed service, disabled/stopped backup timer, disabled
R2 copying, or missing/invalid/overdue local and remote success timestamps.
Freshness allowances are 20 minutes for CWL, 45 minutes for Mongo, and 30 hours
for daily restore verification. Inspection failure is itself an incident.
An independent lock allows this monitor to detect backups stuck holding the
backup lock. No production data is changed to simulate failures.

Healthy checks are silent. Changed incidents alert once; unchanged incidents
repeat after six hours; recovery alerts once. Notification state is persisted
only after successful delivery. Failed delivery fails the service and retries
on the next scheduled check; transport timeouts can cause a duplicate message.
Messages contain fixed operational descriptions, never raw logs, credentials,
player records, or mass mentions. `monitor-health.json` and
`monitor-notifications.json` live in the private backup state directory.

Eight focused backup/monitor tests passed, covering stale remote backups despite
successful local backups, disabled timers, immediate failed-job detection,
notification deduplication/recovery/reminders, delivery retry, and SQLite backup
safety. The production monitor ran under systemd with no current issues.
The monitor timer is enabled for boot; no host reboot was performed.

Limit: this is an on-host monitor. A complete host failure, internet outage, or
failure of this monitor itself cannot reliably notify Discord. A separate
external dead-man monitor is still needed for those failures. An unconfigured
alert destination is explicitly logged and local health checks continue.

### External host-outage detection integration (prepared, awaiting account)

The same monitor supports the established hosted Healthchecks.io service. No
independent monitoring account/API credential/Ping URL was found on this host.
**External outage detection is not active until the following setup is done.**

In a user-owned Healthchecks.io account, create a check named `CWL backups`,
period **2 minutes**, grace **8 minutes**. Connect the check's Discord integration
to the already selected channel `947166650321494067`; delivery then originates
outside this host and does not depend on the bot process running here. Store the
check's UUID Ping URL as `CWL_BACKUP_HEALTHCHECK_URL` in the existing private
`.local/cwl-backup-alerts.env`, preserving `CWL_BACKUP_ALERT_CHANNEL_ID`. Do not
put the Ping URL in Git or public chat. This file is included in encrypted CWL
backups. No additional timer or bespoke remote service is required.

A healthy monitoring pass pings the UUID URL; detected backup issues ping `/fail`.
Known issues are sent to the external check before attempting local Discord
notification. Failure of the external service does not suppress local Discord
alerts. A healthy heartbeat is sent only after inspection/notification
processing succeeds. A missed heartbeat becomes an external alert after the
configured period plus grace (approximately 10 minutes after the last ping).
This covers loss of the host/network or monitor process, unlike the local timer.
It is backup/monitor heartbeat coverage, not a complete website uptime probe.

Only HTTPS `hc-ping.com` UUID URLs are accepted; redirects are disabled, requests
are bounded, and no logs, account data, or secrets are sent in a request body.
Network errors are sanitized to avoid exposing the private Ping URL in logs.
Unconfigured external monitoring is logged without affecting existing alerts.

Twelve focused backup/monitor tests passed, including healthy/failure heartbeat
routing, rejected endpoints, timeout privacy, and HTTP failure handling. Those
external tests use simulated HTTP responses; **no live external alert-delivery
or host-outage test has been completed**. Once configured, run the monitor,
confirm its healthy state in Healthchecks, and use the provider's integration
test to verify Discord delivery without stopping production backups.

References: https://healthchecks.io/docs/ and
https://healthchecks.io/docs/configuring_checks/.

### Guided member signup (2026-10-14)

The normal signup page now separates three steps: choose Main/Lazy, select linked
accounts, then review and submit. A yellow progress guide shows the current step
with arrows; Back/Continue controls retain choices within the same pool. Choosing
a different pool clears that draft as before. Review is an inline page step,
with an explicit account-count submit button and visible submission errors.
Mobile controls stay sticky, and step headings receive keyboard focus.

Account selection includes TH icons; Lazy league questions appear only for
selected accounts. Existing move consent and hidden-by-default signed-up accounts
are preserved. My signups remains accessible above the guide. Completion explains
staff assignment and that the member can close the page, with View my signups and
Sign up more accounts actions; another signup starts at step one.

Validation: production frontend build and all 34 frontend tests passed. Isolated
browser fixture testing at mobile 390x844 and desktop 1365x900 covered Lazy signup
with a league preference, Main signup with two different accounts, Back preserving
selection, hiding signed-up accounts, completion, restarting the flow, and viewing
all three saved accounts. No live member signups were created. Deployed frontend
entry: `index-RzjP-9c-.js`; public site serves the new build and web service is
active. Previous assets preserved in the private deployment backup directory.

### Contrast correction and staff acceptance check (2026-10-14)

User-reported live screenshots showed light text on the yellow signup banner
and navigation. Replaced those surfaces with dark/blue backgrounds and explicit
light text via final-loaded contrast.css. Signup guide is smaller; selecting
Main/Lazy now immediately advances to account selection. Production entry is
`index-B_8AnUej.js`. Build, 34 frontend tests, and desktop/mobile fixture visual
checks passed. No browser-specific cause is claimed from screenshots alone.

The staff acceptance suite passed 174 tests covering CWL backend workflows,
Manage integration, reminder scheduling, and backup monitoring. Whole-season
trial exercised signups, pool moves, weights, automatic placement, publication,
member visibility, participation, bonuses, export, and archive in isolation.
Manage checks exercised shared delivery receipts, concurrent-send protection,
stale edits, unknown outcomes, and restart recovery with simulated transports.

Read-only live audit: SQLite integrity OK, no foreign-key errors; November 2026
had 58 signups and 2 assigned accounts; no published roster and no explicit
Manage campaign binding. Bot worker heartbeat was 10 seconds old. Thus the live
season is not ready for a real roster delivery. No real campaign binding,
placement, publication, or announcement was changed by this trial. A complete
live send has not been claimed or performed.

### Staff workflow and readiness recheck (2026-10-14, evening)

After the signup-guide browser color mitigation, reran the isolated backend
acceptance/integration/backup suite (174 passed) and frontend suite (34 passed).
The backend suite covers whole-season placement/publication/member visibility,
shared Manage settings, concurrency, duplicate receipts and retry recovery.
These are isolated tests, not a real Discord announcement delivery.

Read-only production audit: SQLite integrity OK, zero foreign-key errors;
November 2026 has 58 signups, 2 assignments, no publications, and no explicit
Manage month binding. Four hosting clans exist and are unarchived; only Lazy .125
is explicitly in the season lineup, and no lineup rules are configured.
The bot delivery worker heartbeat was 9 seconds old. Web, bot, and tunnel are
active. Backup freshness checks reported no issues; the backup monitor timer is
active and enabled, with a configured Discord alert destination.

External host-outage monitoring remains unconfigured (no Healthchecks Ping URL).
An off-device recovery-key copy cannot be verified from this host. Live roster
placement, campaign binding, publication and Discord sends were left untouched.
Before real publication staff must configure season lineup/rules, review
remaining placements, and select the matching Manage campaign month.

### Member dashboard home (2026-10-14)

Added Home as the default signed-in landing page, preserving explicit assignment
deep links. General member branding is separate from the CWL navigation section.
Home provides personal account totals/status filters, name/tag/clan search, TH
sorting, current-clan groups with official Clash badges and graceful shield
fallbacks, TH emojis, provisional placement labels, and staff navigation shortcuts.
Account results are paginated at 12 per page. Unsigned accounts can be selected
across filters/pages and carried into the existing Main/Lazy signup review; signup
validation, pool-move consent, and authorization remain on the existing paths.
Already signed-up accounts link to signup management or assignments.

Home polls every 30 seconds while visible, supports pause/manual refresh, and
keeps its last successful snapshot on failure. Season closure status refreshes
with the data. Selection is preserved unless an account becomes signed-up or is
no longer linked. Authenticated /dashboard/accounts snapshots are cached per user
for 60 seconds, with concurrent refresh coalescing, expired-entry pruning, a
1,024-user bound, failure retry and shutdown cancellation. Clan image URLs are
limited to the official Clash HTTPS badge asset host. No new database schema or
bot changes were needed. Existing persistent web service hosts the update.

Validation: 180 backend tests and 37 frontend tests passed, production build and
diff whitespace checks passed. Desktop/mobile fixture browser checks covered
selection persistence on refresh, Lazy signup with preference, two-account Main
signup, returning to updated home, automatic appearance of a staff placement,
and keeping data visible when the fixture server was stopped. At 390px viewport
there was no horizontal page overflow. All submissions used a separate fixture
SQLite database, never production. Public HTML serves index-CZU-fGdO.js; endpoint
returns 401 without authentication and the web service is active.

This release adds the Todo-style account dashboard for current CWL workflows;
the activity feeds were added in the subsequent Todo release below. Live season setup and external outage-monitor configuration
remain the separate readiness items documented above.

### Four-clan horizontal comparison (2026-10-14)

Compare clans now supports two, three, or four simultaneous columns, defaulting
to up to four active hosts. The comparison region scrolls horizontally on narrow
screens while the rest of the page stays fixed horizontally. A–D buttons jump to
columns; dropdowns can reorder displayed clans without duplicates. Sorting and
clan summaries remain shared. Staff can select one account from each of any two
columns, review, and use the existing atomic swap and undo workflow.

Verified four visible columns at 1600px and contained horizontal scrolling at
390px with no page overflow. An isolated fixture swap between columns A and D
succeeded, retained manual placements, and exposed the existing undo action.
Column reorder verified. Build, 37 frontend tests, and diff checks passed.
Frontend index-ZHrPJ6RD.js deployed with prior assets retained. No live roster
assignments were altered by testing.

### Website Todo activity feeds (2026-10-14)

Todo is available from the sidebar and Home shortcut. The authenticated endpoint
`/api/cwl/todo` resolves only the session user's linked accounts and reuses the
bot's war, CWL, raid and private-log view builders. Historical clan candidates
are read without creating Mongo indexes. Snapshots are cached per user for 60
seconds with coalescing, bounded cache size and cancellation on shutdown. Total
provider failures return 503 without caching a false empty success.

The UI supports account multi-selection, search, sorting, clan groups/badges,
TH icons, progress, deadlines, pause and manual refresh. Refresh keeps filters
and preserves the last successful data on failure. Missing/private/partial
activity is explicitly distinguished from completed activity.

Clan Games uses ClashKing v2 player history/stats current-month observations
and the existing 1,000-point family goal. Recorded activity may lag or be absent;
unknown scores remain null and direct members to check in game. These are not
authoritative live totals, and no event schedule is inferred. A read-only live
smoke test with two linked accounts returned war activity and correctly marked
both absent Games histories as unknown.

Validation: 323 backend tests, 40 frontend tests and production build passed.
Fixture browser checks verified account filtering, refresh selection retention,
Games progress and mobile layout at 390px without horizontal page overflow.
No live signup, roster, announcement or game-state mutations were performed.
Production frontend: index-FeZOYLdh.js. Restart only wu-cwl-demo-web.service
for backend activation; the Discord bot continues independently.

### Todo return links and saved preferences (2026-10-14)

`/?view=todo` opens Todo directly and preserves that destination through Discord
sign-in using session storage. Explicit assignment links retain precedence over
a stored Todo return; abandoned returns are consumed or cleared. Navigating away
removes the Todo route so refresh does not reopen the wrong page.

Todo activity, selected account tags and sort order are saved in browser local
storage per Discord user ID. Preferences survive navigation and reload, never
grant access to accounts, and do not affect source data. Invalid or blocked
storage falls back to defaults. This is browser-local, not cross-device sync.

44 frontend tests and production build passed. Fixture browser verified direct
entry, Clan Games selection, one-account filter and TH sort surviving reload,
and clearing the Todo URL on Home navigation. Frontend-only release; no bot or
web-service restart required.

### Live launch rehearsal and recovery check (2026-10-14)

Read-only live audit: November 2026 remains open/draft with 58 signups (56 Lazy,
2 Main), 2 assigned and 35 total missing weights. Four unarchived hosting clans
exist (.122, .123, .124, .125); only .125 is explicitly in the season lineup.
No placement rules, Manage month binding or publication exists. Automatic
placement preview proposes zero moves: 22 unassigned accounts lack eligible
rules and 34 lack weights. Existing placements were preserved.

Read the existing November Manage campaign without changing it. The bot-owned
worker is healthy. Main destination is 1072714594625257502; Lazy destination is
865726525990633472. Both have announcement text; no roster delivery recorded.
Roster buttons still point to legacy Google spreadsheets, and Lazy retains its
separate guide link. Before launch, bind the confirmed campaign month and review
changing roster buttons to the web assignments link while preserving the guide.

79 isolated season-trial, Manage/bridge, scheduler and backup tests passed.
Local AND R2 repository data checks and isolated SQLite/Mongo restores passed;
Mongo restore verified 55 collections and 9,004 documents. Production databases
were not restored or modified. Web and backup/monitor timers are active, latest
backup monitor reports no issues. External host-outage monitor remains unset;
off-device recovery-key custody still requires operator confirmation.

Await operator choices: per-clan capacities, weight bands and lower-league
classification, Main host, and explicit campaign month. Do not invent these
rules or publish the currently incomplete draft. No real announcements sent.

### Recovered mockup placement rules (2026-10-14)

Recovered original `cwl-redesign/base-mockup.html` seed: 15-player example clans,
174k+ Unranked and 160k <= weight < 174k Master II. Original clan names were
.70/.71 and generated successors, not real .122–.125 mappings. Read-only Clash
API confirms .123/.124/.125 are Master II, while .122 is Master III; no active
hosting clan is Unranked. Under the user's explicit request to restore mockup
configuration, applied Lazy/15/160000–174000/exclusive maximum/lower-league=false
rules to those three verified Master II clans only. Rules were absent before
update; existing rules are never overwritten by the recovery script. One
transaction, revision bump and hosting_rules audit entries attributed to
`codex:user-request`; private before-change SQLite snapshot retained.

Current saved-data preview proposes 4 moves, leaving 18 without eligible rules
and 34 missing weights. Preview only: no assignments or publications changed.
Live FWA source lookup independently found 24 weights (6 in the recovered band,
18 below 160k, none >=174k). A live lookup is not a saved weight refresh.
Need operator rules for Master III .122 and sub-160k players, an Unranked host
if using that band, and Main hosting. The mockup did not define these decisions.

### FWA outcomes in website Todo (2026-10-14)

War clan headers show FWA WIN/LOSE, opponent name and BLACKLISTED precedence.
Shared utils/todo_fwa.py extracts the existing bot record lookup and matching
logic; Discord wrappers retain their interface and pass existing regressions.
Only matching war-end timestamps (within 60 seconds, naive timestamps treated
as UTC) expose an outcome. Missing/stale records do not produce a verdict. Web
queries fail closed if the live blacklist cannot be checked, retaining attack
rows and showing a source-unavailable note. The read-only lookup uses the
existing routed Mongo collections and Todo's per-user refresh cache.

80 backend and 44 frontend tests passed; fixture browser verified War-only
label and mobile layout at 390px. Frontend index-hlmJhJ4w.js. Restart only the
web service; no Discord announcements, roster edits or bot restart required.

### Discoverable clan range editing (2026-10-14)

Roster builder now exposes Edit clan ranges beside placement preview, opening
a compact clan selector above comparison instead of the buried all-clan list.
Staff edits per-season min/max weights, pool, capacity and lower-league match
through the existing revision-checked API. Blank bounds are unlimited; maximum
is exclusive. Existing assignments are unchanged by rules edits. Editor keys
include season/clan/revision so refresh does not retain stale server values.
44 frontend and 22 roster backend tests passed. Fixture UI saved a custom
150k–180k range and 30 capacity successfully. No production rules changed by
this UI release. Deployed index-arTexMKm.js; frontend-only update.

### Focused missing-weight queue (2026-10-14)

Roster toolbar exposes Needs weight with a live count. Focused view replaces
comparison/assignment cards with searchable, paginated rows (10 per page), TH
icons and quick manual entries. Bulk refresh intentionally checks all season
signups using the existing source-refresh endpoint and preserves manual weights.
Manual entries use the existing validated revision-checked/audited PATCH, remove
resolved accounts from the queue after refresh and never change placements.

44 frontend tests, 22 roster tests and production build passed. Fixture browser
saved 170k for an assigned account; it disappeared from the queue. Subsequent
source refresh produced 159k while retaining the 170k override and the same
clan assignment. All-clear state verified. No live weights changed by testing.
Frontend-only deploy index--v1Pnb6f.js; existing backend unchanged.

### Sidebar overflow fix (2026-10-14)

Sidebar now has viewport height, independent vertical scrolling and visible
scrollbar styling. Desktop sidebar stays sticky; mobile stays a fixed drawer.
Children do not shrink, preserving all menu items and Sign out. Mobile open
drawer locks background page scrolling; overscroll stays inside the sidebar.
Build passed. Fixture browser at 1200x600 and 390x600 verified scrolling to
Sign out; mobile sidebar scrolled 359px with page scroll staying zero. Access
button at the bottom opened its page and closed the drawer. Frontend-only
release index-7McSYy0p.js; no data or service changes.

### Hosting defaults and display snapshot cache (2026-10-14)

Hosting directory now accepts Main/Lazy on add and edit. Nullable clans.pool
migration preserves existing data; per-season explicit rules override this
default. Staff authorization, audit events and season revisions remain enforced.
No live clan pool decisions or placements were changed during deployment.

Home and Todo hydrate user-scoped localStorage display snapshots (Home also
season-scoped), valid for five minutes, then refresh in the background. Cached
state is labeled; Home signup selection waits for fresh data. Successful writes,
sign-out and 401/403 clear snapshots. Blocked/full storage degrades gracefully;
no authentication tokens are stored in these snapshots. Expired snapshots are
ignored. This reduces repeated page-opening blank states, not initial sign-in
or the first uncached fetch.

138 backend web tests and 46 frontend tests passed; production build passed.
Fixture browser verified pool update, then stopped the fixture server and
reopened Todo/Home: saved tasks/accounts remained visible with refresh-failed
status. Corrected Home cached copy to avoid claiming signups are closed.
Backed up SQLite and prior frontend, deployed index-B7UBHYfP.js and restarted
only wu-cwl-demo-web.service. Public release hash, service active, pool migration,
and unauthenticated Todo 401 verified. Discord bot was not restarted.

### Expandable dashboard navigation foundation (2026-10-14)

SidebarNavigation centralizes working page groups: Home/Todo shortcuts, member
CWL, staff-only CWL management, and owner-only Server settings (Access).
Expansion preferences are user-scoped and tolerate unavailable browser storage.
Navigating into a section expands it; users can collapse it again. Current page
and its parent group have distinct highlighting. Breadcrumbs reflect sections,
including Server settings rather than CWL for Access. Existing navigation
handlers still close the mobile drawer and retain all existing page behavior.
No placeholder sections, new permissions, database changes or bot restarts.

46 frontend tests and production build passed. Fixture UI confirmed expansion,
reload persistence, and 390x600 mobile drawer navigation to Seasons & clans,
which closes the drawer. Existing scroll containment remains. Deployed
index-fZLoMN7N.js atomically with a previous-frontend backup; public hash verified.

### Autonomous completion audit (2026-10-14, after navigation release)

Revalidated the existing whole-season workflow, member isolation, publication,
Manage integration, reminder scheduling, and backup monitoring with 198 passing
backend/integration tests. These tests use isolated fixtures/simulated delivery;
no production announcements or roster mutations occurred. Existing aiohttp
AppKey/test-fixture deprecation warnings remain non-failing technical debt.
Live SQLite integrity is OK with zero foreign-key violations. Public site returns
200; web service active with Restart=on-failure. Web and all four backup/monitor
 timers enabled; user linger enabled for startup without interactive login.
Backup monitor checked 2026-10-15T02:18:09Z and reported no issues. No host reboot
was performed. External Healthchecks configuration and off-device key custody
remain operator dependencies; actual roster policy and publication remain staff
choices. No new critical implementation blocker was found in these checks.

### Shared signup messages and reminders editor (2026-10-14)

CWL management → Messages & reminders uses the same Mongo campaign and native
Manage draft/save/schedule functions. Staff explicitly binds a web season to its
CWL campaign month. Editor covers Main/Lazy titles, body, image reference, channels,
role mentions (guild-validated), enable switches, timezone, signup opening and
closing rules, individual reminder times, evenly spaced/interval sequences,
optional future-month recurrence, preview, shared pause/resume and activity history.
Changes require preview and in-page confirmation. Existing sent-message protection,
revision/generation checks, CSRF, editor authorization and archived-season guards
remain. Unsaved edits are warned before navigation. Existing signup button links
are displayed read-only, excluded from frontend patches and rejected server-side.
No production campaign edits or signup-link migration were performed.

The existing bot worker polls for native campaign revision changes and invokes
its existing scheduler reconciliation, recording the loaded generation only after
success. Failures retry and do not block the independent roster delivery queue.
The web shows bot acknowledgement separately from saving. No second scheduler
was introduced. Website signup_open and external form availability are deliberately
unchanged; their current gate and campaign window are shown for launch review.

252 backend/native integration tests and 49 frontend tests passed. Fixture browser
verified edit→preview→save, locked original form URLs, evenly spaced sequence
preview/save, role choice, and mobile 390x844 layout. No real Discord test messages
sent. Deployed index-BR9LfjvP.js; backed up frontend and exactly three bot files
(utils/cwl_campaign.py, utils/cwl_web_bridge.py, extensions/tasks/cwl_reminder.py).
Restarted web and bot. Both active, public hash correct, unauthenticated settings
401, live bot reconciliation acknowledged, campaign-content hash unchanged before
and after deployment. Existing signup links remain awaiting explicit launch approval.

### Opt-in phone reminders (2026-10-14)
- Todo has device-specific Phone reminders with linked-account selection, War/CWL toggles and 6h/2h/30m thresholds. Browser permission is requested only on explicit enable.
- Notifications aggregate unfinished selected accounts by clan/war/deadline, never one notification per account. Fresh reads bypass Todo caches. SQLite claims prevent duplicate sends across process restarts; overdue deadlines are skipped rather than replayed.
- Root service worker handles push and opens Todo; it does not cache authenticated pages/API data. Logout removes the current device subscription. Expired subscriptions are cleaned up.
- VAPID private identity is stored outside source in `.local/cwl-web-data/push-vapid-private.pem` (0600). Existing encrypted backup staging includes `push-vapid-private.pem` alongside `cwl-web.env`; restore both together to preserve existing subscriptions. Local and R2 backups completed after deployment.
- Validation: 244 backend checks and 58 frontend checks passed; production build, mobile layout, origin asset MIME/scope, unauthorized API protection and SQLite migration checked. No member was opted in and no live notification was sent. Real handset receipt requires the member to enable notifications and use Send test notification.
- Dashboard user service remains enabled with restart-on-failure. Bot service and existing signup URLs were not changed.

### Comparison and custom reminder controls (2026-10-14)
- Staff comparison supports 2–10 active hosting clans, retaining four initial columns and isolated horizontal scrolling.
- Phone reminder times use native Hours/Minutes selects, 1 minute–24 hours, up to five distinct times. Existing saved times remain intact. Server validates bounds, types, duplicates and count; delivery still groups by clan.
- Validation: 14 push backend tests, 58 frontend tests, TypeScript and production build passed. Public deployed bundle verified.

### Recurring reminder editor (2026-10-14)
- Messages and reminders no longer requires a roster month binding. Reads and writes resolve the native Manage current month automatically; roster announcement bindings remain separate.
- Web saves always request monthly recurrence, reusing Manage's existing conversion, concurrency and sent-message protections. Preview/history show their month only for context. No live configuration was changed during deployment.
- 15 Manage bridge/reminder backend tests and 58 frontend checks passed, including unbound editing and next-month inheritance. Production build and public bundle verified.

### Clan CWL leagues (2026-10-14)
- Hosting/family directories, roster destination selectors and comparison cards display Clash API warLeague names; clans without ranking display Unranked.
- Clan metadata is cached for five minutes with bounded concurrent reads. Failed lookups retain labeled last-known values or show League unavailable, never falsely Unranked. No placement rules or user assignments are changed.
- 54 affected backend tests and 58 frontend tests passed; production build and public bundle verified.

### League sorting and filters (2026-10-15)
- Clan directories and comparison offer league ascending/descending sorting with correct tier/division order; Unranked and unknown values follow ranked clans.
- Expandable multi-select league and Town Hall filters support comparison and roster account lists. Directories support league filtering. Counts, empty states and Clear filters are visible; narrow layouts wrap controls.
- Comparison TH filters hide players but leave capacity/average totals intact. Roster league filters refer to assigned hosting clans, excluding unassigned accounts only while league filtering. Filter changes clear pending account selections.
- 61 frontend tests, TypeScript and production build passed; isolated fixture browser layout and public deployment verified. No live assignments changed.

### Roster workflow redesign (2026-10-15)
- Assign accounts is the default focused view; Compare clans, Clan settings and Weights have separate controls. Comparison retains ten clans, filters and sorting. Auto-placement still requires preview/apply.
- Account rows show TH icon, name, weight and assigned clan; individual controls and source detail expand on demand. Additional filters collapse under one disclosure.
- Lists show 20 accounts per page, preserve selection across pages, reset selection when filtering, and expose selected-account actions in a sticky bar. Existing assignment, undo, capacity, concurrency and manual weight APIs are unchanged.
- 61 frontend checks, 24 backend roster tests and production build passed. Isolated fixture browser checks covered assignment success, pagination and mobile action-bar visibility; public deployed bundle verified. No production assignments were changed.

### Placement explanations and direct assignment (2026-10-15)
- Read-only live diagnosis: 18 unassigned weighted accounts were 133k–159k, below the three configured clans' 160k inclusive minimum. Three additional hosts had no automatic capacity/range settings; 33 accounts lacked weights. No saved rules or assignments were changed.
- Roster response now attaches exact planner reason and explanation to unassigned accounts; preview uses those explanations. Each account has an explicit Place manually / Move account inline editor with Save placement, active destinations, and full-clan labeling.
- Automatic eligibility remains unchanged. Regression verifies a 159k account cannot auto-place into a 160k minimum but can be placed manually by staff. 26 placement tests, foundation checks, 61 frontend checks and production build passed; public deployment verified.

### Intermittent Mongo dump investigation (2026-10-15)
- Journal confirms two mongodump failures: Oct 14 22:02 EDT and Oct 15 07:17 EDT, each followed by success at the next 15-minute run. 64 successful Mongo backup runs were present at investigation time; failed stage was dump creation, before Restic/R2.
- Exact historical Mongo errors cannot be recovered: command() overwrote last-tool.log for each subsequent command, and *.log is excluded from snapshots. No corresponding network-service events or bot error signatures were found in the inspected 07:16–07:19 window. Current disk usage does not indicate pressure. These observations do not establish the original dump failure cause.
- Fixed diagnostic retention: each failed command/timeout retains a separate 0600 file inside a 0700 tool-failures directory, bounded to 100 failures. Successful command logs are removed. Journal errors name only the private log file, never raw output or credentials. Alerts remain unchanged; no failure is suppressed.
- 14 backup/monitor checks passed. Fresh live Mongo backup completed locally and in R2 at 10:27 EDT; intermittent failure did not reproduce.

### Phone reminder readability — 2026-10-15
- Clan notifications now lead with total attacks remaining and account count, followed by up to three named accounts with explicit attack counts and an overflow count.
- War/CWL icons distinguish events; mixed hour/minute offsets retain their minutes. Long names are bounded and whitespace normalized.
- Clan grouping, durable delivery deduplication, saved preferences and Todo click destination are unchanged.
- Validation: 15 push tests passed, including summary totals, singular wording, overflow, mixed durations and restart deduplication. Device rendering remains controlled by the OS.

### Persistent login — 2026-10-15
- User approved extending the fixed session duration from 15 minutes to 30 days. Both the database expiry and HttpOnly/SameSite cookie lifetime use the same duration; production Secure cookies remain enabled.
- Applies to new logins; existing sessions retain their original expiry. Explicit logout immediately revokes the session. No expired sessions are restored.
- Validation: 43 foundation/push tests passed, including 29-day access, 31-day rejection, cookie lifetime, and rejection after logout.

### Launch readiness audit — 2026-10-15

User confirmed real trigger delivery, signup → assignment → member view, and
opt-in phone reminder checks. Existing signup links remain unchanged until the
user explicitly approves migration.

- 327 dashboard/backend checks passed across CWL workflows, scoped access,
  command builders, backup monitoring and shared Manage integration. Earlier
  frontend run: 106 passing tests. No production member data or messages were
  changed by the audit.
- Live SQLite integrity OK, zero foreign-key violations. Web and bot active;
  web restart-on-failure enabled. Web, bot, Cloudflared and backup timers enabled;
  user linger enabled. No host reboot was performed.
- Local/R2 backup timestamps current; backup monitor reports no incidents.
  Isolated restore from the encrypted R2 repository verified SQLite and 58 Mongo
  collections / 9,018 documents, including collection indexes and options.
- Closed the new artwork recovery gap: CWL snapshots now include objects under
  the public media bucket's `content/command-triggers/` prefix. Only new/changed
  objects are downloaded; cached bytes are checksum-checked. Restic encrypts and
  copies these with the existing CWL snapshot. Archived/removed artwork is not
  deleted from this recovery cache. The manifest maps original R2 keys to local
  filenames and SHA-256 hashes. Restore checks verify every captured image.
  This does not claim to back up unrelated public media bucket objects.
- Artwork capture failures fail the backup visibly instead of reporting false
  protection. Existing monitor catches failed/overdue runs. Sixteen focused
  backup tests passed; first live capture protected two images and copied to R2.

Remaining operator dependencies: configure an external Healthchecks ping URL
(the adapter already exists) to detect complete host/network outages; keep the
Restic encryption password in an off-machine password manager/recovery kit;
explicitly approve any signup-link migration. The agent cannot establish external
account ownership or verify off-machine key custody on the user's behalf.
- Follow-up off-site restore verified both captured command images by SHA-256,
  plus SQLite and Mongo again. Public dashboard returned HTTP 200. Private
  environment files and the recovery key have owner-only (0600) permissions.
  To recover artwork, restore `command-images/` into scratch space, verify its
  manifest, then upload each hashed file to its original manifest object key in
  the public media bucket; preserve the public base URL. Do not overwrite live
  objects as part of a recovery test.

### Family clan management (2026-10-15)

Server settings → Clan management edits the bot's routed `clans` collection
(currently `settings.clan_data`), not a second directory. The `clans` dashboard
permission is separate from CWL management. Owners retain full access.

The editor supports adding by Clash tag, removing with typed confirmation,
name/type/minimum TH/profile, leader and role selection, channel assignments,
logo/banner uploads or URL import, emoji replacement, and thread creation/reuse.
Edits compare the prior record before writing, retain snapshots in
`settings.clan_dashboard_history`, and preserve unrelated fields. Idle browser
editors refresh every 30 seconds; unsaved changes are retained. Reopen an old
Discord panel to see fresh values. This is shared storage, not push updates to
already-sent Discord messages.

Emoji and thread work uses the existing durable management worker, which
rechecks authorization before executing. Both interfaces use the shared emoji
and thread helpers. New emoji are created before replacing the stored reference;
old emoji remain available to published messages. Application emoji limits still
apply. Clan threads use the existing Discord clan thread parent.

Removing a family directory entry does not delete CWL season history, separately
configured hosting clans, Discord roles/channels, or uploaded artwork. This avoids
silently damaging current rosters or messages. Web role fields configure which
roles the bot uses; saving them does not bulk assign roles to members.

Validation: 135 targeted backend checks, 106 frontend checks, production build,
desktop fixture save/reload, 390px mobile layout (no horizontal overflow), and
read-only live database/worker checks. No production clans or members were edited
for testing. Deployment rollback copies are in `.local/pre-clan-management-*`
and the botrunner equivalent. No signup announcement link was changed.

### Clan activity and recovery (2026-10-15)

Clan management → Activity & recovery provides searchable, paginated snapshots,
source/actor/time, expandable saved settings, and a typed-tag restore review.
History reads and restores require the existing `clans` permission; restores also
use normal CSRF protection. Only the latest removal snapshot for a missing clan
is eligible. Restoration inserts the original record under the unique tag index;
it never upserts over a current clan. Duplicate or stale restores are rejected.
Snapshots and restore events share `settings.clan_dashboard_history`. Timeline
and clan/action indexes support bounded queries. History has no expiry.

Discord clan add, edit, artwork, emoji, thread and removal paths now record
snapshots too. Discord removal keeps artwork/emoji and records the recovery copy
before deleting the record. Both interfaces preserve CWL history and Discord
roles/channels. Restore only restores saved settings: it does not recreate deleted
Discord resources or grant member roles. Staff should review old resource links.

Snapshots are explicitly labeled as saved before changes, not proof of success.
Old operations are visible/recoverable only when a snapshot already exists. No
historical Discord activity is fabricated or backfilled. Read-only settings are
not exposed beyond the clan management permission.

Validated with backend permission, conflict, native-removal, snapshot-failure and
restore-race tests; frontend suite/build; browser fixture restore end-to-end and
390px mobile inspection. No production clan changes were made for verification.

### Navigation groups (2026-10-15)

The sidebar now groups personal pages under My dashboard, staff season work under
CWL, the family directory/history under Clan management, daily server operations
under Server tools, and integrations/staff access under Settings. Existing view
IDs, API authorization, grants, Mongo records and Discord actions are unchanged.
Empty groups are hidden. Expansion preferences use a new per-user v2 key and the
active group opens automatically; groups remain keyboard accessible and the
mobile drawer retains independent scrolling. Activity & recovery is now reached
through Clan management → Family clans → Activity & recovery.

Validation: all 106 frontend checks passed, production build passed, and desktop
plus 390px phone checks covered group expansion, saved preferences and navigation
into Staff access. This release only replaces frontend assets.

### Staff overview (2026-10-15)

My dashboard → Staff overview is visible to staff with any explicit dashboard
scope (and owners). The read-only `/manage/staff-overview` endpoint rechecks both
local/shared grants. It shows unplaced signups from active SQLite seasons, current
thread-runtime open application counts, and the caller's failed/unconfirmed
management requests from the last seven days (latest five details). It does not
claim that past failures remain unresolved. Ticket aggregates/console link also
require the existing native Discord recruiter/admin check in the configured
guild. Recruitment message or ticket settings access alone does not expose them.

Roster actions select the correct season; ticket actions use the existing Discord
console; failure review opens the relevant tool. No ticket decisions, Discord
sends, retries, or settings changes occur on this page. Refresh is every 30 seconds
while visible, with pause/manual refresh and last-successful data on transient
errors. Unauthorized responses clear displayed data. Responses use no-store.

Validated: 106 frontend checks; 14 backend access/summary checks including actual
SQLite counts, archived seasons, scope isolation and recruiter gating; desktop
and 390px browser inspection; read-only live ticket configuration/count checks.

### Final readiness and recovery audit (2026-10-15)

- Passed 342 backend workflow/access checks, all 106 frontend checks, and 18
  focused backup/monitor checks after the artwork fix.
- Expanded encrypted artwork capture beyond command triggers to `clans/`,
  `fwa/bases/`, and `content/recruit/`. Empty R2 directory markers are skipped;
  empty image objects and oversized objects still fail visibly. Regression tests
  cover prefix coverage, caching, checksums, markers, and invalid image sizes.
- Fresh production backup completed successfully with 54 artwork files. An
  isolated restore from R2 verified all 54 file hashes, SQLite integrity/table
  counts, and 59 Mongo collections containing 9,014 documents. Production data
  was not restored or overwritten. The initial expanded capture encountered R2
  directory markers; this was fixed and the failed job rerun successfully.
- Live SQLite passed integrity and foreign-key checks across 32 tables. Public
  dashboard returned 200; unauthenticated staff summary returned 401. Web and
  bot are active, restart automatically, and are enabled at boot. All four backup
  timers are enabled; user linger is enabled. No physical reboot was performed.
- Remaining operator dependencies are unchanged: keep a copy of the backup
  encryption password outside this server (phone password manager or securely
  stored paper is sufficient); configure the existing external outage-monitor
  adapter with an owned Healthchecks endpoint; explicitly approve signup-link
  migration when ready. The encryption password unlocks Restic backups, not
  Discord accounts. Its presence on this server cannot establish off-site custody.

### Dashboard welcome and direct member links (2026-10-15)

Welcome now describes the full server dashboard: accounts, attacks/events,
reminders and CWL. Short feature descriptions, a single Discord sign-in action,
and a destination hint replace the CWL-only introduction. Reviewed labels using
W3C descriptive-label guidance (https://www.w3.org/WAI/WCAG21/Techniques/general/G131.html).
Member labels now use To do, CWL signups, My clan assignments, Waiting for a clan,
and May change. Staff workspace labels read Staff tools.

Share `/?view=signup`, `/?view=todo`, `/?view=assignments`, or `/?view=home`.
Signup/assignment links may include a numeric `season`; unavailable seasons show
an explicit warning. Copy page link includes the current member page and season.
Direct entry and refresh preserve the member page. Login uses a five-minute
HttpOnly, SameSite=Lax, production Secure cookie for an allowlisted local return
page; success and browser-error redirects preserve it and clear the cookie.
This works without sessionStorage. Unknown/external destinations are rejected;
OAuth state validation and all existing access checks are unchanged. The existing
Discord signup announcement URLs were not changed.

Validation: 353 backend checks, 109 frontend checks, production build; mocked
OAuth success/failure destinations and malicious destination inputs; desktop and
390px welcome inspection, signup entry, clipboard confirmation, assignments
refresh, no horizontal overflow. Deployment preserved prior static assets and
saved the prior frontend/backend mirror. Public root/current build, unauthenticated
staff protection, and Discord authorization redirect verified after deployment.

### Prominent signup controls and staff adds (2026-10-15)

Staff with CWL access now see a season-labelled status/action bar at the top of
Roster builder, CWL signups, and Seasons & clans. Open/Close signups explicitly
covers Main and Lazy and confirms the selected season. Existing signups remain.
Archived seasons disable these controls.

Add signup uses the existing searchable member picker with a separate CWL-only
read endpoint, then loads the selected member's linked accounts. Staff select
multiple accounts and Main/Lazy; Lazy requires a per-account league answer.
Already signed-up accounts are labelled and disabled. Account names, tags, TH,
and clan come from the existing provider. There is no extra verification gate.
Accounts must be linked to the selected member; no manual ownership claim or
unlinked tag is accepted. No Discord role access is granted by this workflow.

The staff POST allows closed but nonarchived seasons, refreshes account links,
checks the season and duplicates inside a single write transaction, records the
staff actor and saved signup in roster_audit, and bumps the roster revision.
It never overwrites an existing signup or placement. Member signups and roster
read the same rows. UI refreshes after a successful add. No schema change needed.

Validation: 317 backend tests and 109 frontend tests; focused checks for CWL
scope isolation, closed/archived seasons, unverified linked accounts, duplicate
batch atomicity, wrong-owner account rejection, member visibility, audit actor,
and contains-name search. Isolated browser test closed a test season, added two
accounts, and confirmed member signup counts and both roster entries. Desktop
and 390px mobile inspected without horizontal overflow. Production asset/version
and unauthenticated endpoint checks passed; no production signup was changed.

### Staff signup by player tag (2026-10-15)

Add signup now defaults to By player tag; By Discord member retains the existing
bulk linked-account flow. Player lookup retrieves live name, TH, current clan and
reverse ClashKing shared-link owner. Existing owners are selected automatically;
when none exists, staff may leave Discord empty or enable Has a Discord account
and enter an ID / use server member search. This association is season-local and
does not modify global ClashKing links. Staff views label empty owners No Discord
account; no fabricated Discord identifier is stored.

A separate CWL-authorized endpoint rechecks game data and reverse links on save,
rejects changed/conflicting links and duplicates, and permits closed/nonarchived
seasons. Link service failure is distinct from a known missing link and blocks
save rather than guessing ownership. Staff audit records association source and
actor, and the shared roster revision is advanced. Signup/assignment visibility
for a manual Discord association uses the existing user_id field. A player saved
without Discord remains staff-managed until separately associated; this feature
does not automatically claim old unassociated signups after a future link.

Validated 272 backend checks and 109 frontend checks, production build, no-link
signup and linked-owner lookup in an isolated browser, optional ID controls and
390px mobile fit. Tests cover manual member visibility, closed seasons, archive
lock, duplicates, wrong/changing owner, missing links versus lookup outage,
reverse-lookup normalization, and roster inclusion without Discord. Production
assets and unauthenticated lookup protection checked. No live signup was added.
