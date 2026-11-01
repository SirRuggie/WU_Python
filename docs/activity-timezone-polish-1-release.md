# Activity and time zone polish release

Tag `activity-timezone-polish-1`, merge `8087c6917da80b989d619ef34f819085f1af25f8`
(PR116, accepted in handoff 224), went live October 31, 2026 at 21:08:27 EDT.
Claude's read-only production smoke passed in entry 226.

The release adds bounded background Discord identity refresh and named clan
warnings to activity rows, plus daily healing of successful but malformed history
reads. Actual upstream failures retain bounded backoff. Time zone parsing adds
UK/NZT/AET and exact uppercase MT/MTN, normalizes decorated letters/subdivision
flags, and preserves unknown annotations. Signup activity keeps 30-second interval
reads while throttling visibility-triggered reads. No live test messages were sent.

## Verification

- 1,247 frontend tests, TypeScript/build, 5,494 guarded backend regressions with
  26 skips and 221 subtests, 26 relevant rework backend cases, five real-Mongo
  cases, seven original and five rework mutation kills. Eight integrated
  build/layout stages passed; narrow/wide fixtures were inspected.
- An isolated 93-second Chrome observation with visibility events every 100 ms
  read at 0/29.982/59.982/89.981 seconds, with no page errors or non-login writes.
- The clean tagged isolated checkout built immutable frontend assets; 1,801
  backend archive files were checked byte-for-byte. A first staging attempt lacked
  local build tools and created no release directory; locked `npm ci` corrected it.
  Both existing runtime interpreters imported affected modules before activation.
- Bot PID 769256, invocation `561e65f2a8c641ca8b08ca361b650a28`; backend PID 769465,
  invocation `fc19c99a4e964a0d9a03a36985ccf734`. Startup/readiness passed without
  tracebacks. The single bot restart waited 210 seconds for identity leases to
  drain. Backend cwd is the immutable 8087c69 archive; bot cwd remains
  `/home/botrunner/wu-bot` at the exact pushed tag. Config returned 200 twice.
- Public HTML and affected Roster/Strikes assets match the immutable manifest.
  Entry `assets/index-B1XIz_-t.js` SHA-256:
  `ea8e73a63a0ebdb9bf37c67df768a2d7fb3dac5d982529f8abf35fdb25a329fd`.

## Data gates and rollback

The first preflight refused activation before any restart because the 20:27
SQLite baseline had changed: total signups stayed 158, while main 24 → 23 /
lazy 134 → 135, lineup rules 7 → 8, and roster values changed. Those existing
changes were preserved. Fresh 21:04 SQLite and Mongo backups passed integrity,
hash and exact-count checks and an isolated Mongo restore; the owned fixture
stopped. No data was restored to production.

The new baseline has main 23 / lazy 135 signups, assignments 23/134 and locks
23/119. Protected Mongo state stayed exactly 3,560 active strikes on 301 accounts,
581 strike profiles and 274 replacement-eligible accounts, including exact streak
values, through stop, bot start and final activation. SQLite and unrelated systemd
drop-ins matched the refreshed baseline. Evidence is under
`/tmp/wu-polish-release`, including backup-refresh-diff, verified backup manifests,
protected snapshots, startup logs and `live.json`.

Retained rollback: bot `df1ef46ea683dbfa3ca8c8f2c399e7b3fd2fb95a`; backend and
frontend `95228f9e6df5873c76dfe8e708c6e8e1df794a1b`. Both revisions understand
the B cache schema; preserve cache metadata and all profile/activity data.
A mocked rollback coordinator checked these exact targets and no database
restore/cache deletion. It was not executed against production.

## Read-only production smoke

Claude confirmed the public hash, service PIDs/cwds and zero tracebacks since
21:08. At 360 px, roster signup activity made one read after five seconds and two
after another 35 seconds idle, consistent with the intended 30-second cadence.
Strikes showed 563 accounts, no names warning and no overflow. No writes were
pressed.

The same single console 503 remains unidentified. Current backend diagnostics
contain no corresponding 503 route, and gateway access logging is not enabled;
this does not identify its URL or prove it is an avatar. Requesting the exact
browser request URL is a follow-up, not a claimed diagnosis or a failed smoke.
