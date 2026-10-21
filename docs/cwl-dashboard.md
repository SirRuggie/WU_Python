# CWL Dashboard

Open `/manage` → **CWL**. Administrator permission is required and rechecked on every action. The private editor opens the current month and retains your setup across months and bot restarts.

## Publish Final Roster

Choose **Publish Final Roster** on the opening screen. **Both** is selected initially; Main CWL and Lazy CWL are also available separately. Existing spreadsheet links and saved announcements are reused.

Press **Publish to Both Channels** to send immediately, without a required preview or confirmation. Each audience has optional Edit message, Change link, and Preview controls. Each successful send shows View post. Retry failed announcement sends only failed audiences; successful announcements are not duplicated. Automatic signup reminders can remain paused while publishing a final roster.

## Editing

Messages contains the Main and Lazy templates. Submitted text, link, artwork, channel, and ping-role changes save automatically for future posts. There is no separate Save step. Dismissing a modal cancels its unsubmitted input. Preview never pings members, and saving does not send a message or rewrite an existing announcement.

Artwork supports PNG, JPG, GIF, and WEBP up to 10 MB. Existing Upload replacement, Restore default image, and template customization tools remain available. Saving content does not apply a previously rejected timing edit. Concurrent edits use revision checks.

## Signup Reminders

The screen shows running/paused/problem status, the next send, and the latest delivery result. Choose Main CWL, Lazy CWL, or Both; edit signup opening, closing, and reminder timing. Valid submissions save automatically. Running schedules update upcoming messages; paused schedules remain paused. Use Start Reminders or Pause Reminders separately. New setups do not start simply because a form was submitted.

Choose evenly spaced reminders or an hourly gap. The final reminder is included in the pattern, with an editable lead time before signups close. Minimum spacing remains available. The setup repeats monthly until manually changed and never resets at month rollover. Specific-date inputs also carry forward as monthly rules. Monthly days 29–31 clamp to the last day in shorter months.

Times are entered in the displayed campaign timezone; Discord timestamps display in the viewer's local timezone. Invalid timing retains the previous active schedule and reports the problem. Previously sent messages are not resent. Skip this message retains its confirmation. Failed reminders have a contextual retry action.

## Related tools

**CWL Return Pings** manages saved clan members and return pings, not the published assignment spreadsheet. See [CWL Return Pings](lazycwl-dashboard.md) and the [agreed War Operations decisions](war-operations-ux-review.md).

The retired `/cwl dashboard` and `/cwl rosters` slash-command entry points remain retired. Use `/manage`.

## Dashboard database recovery (2026-10-21)

Production entrypoint `python -m cwl_web` now requires the Mongo recovery head.
SQLite is the relational working copy, not the sole durable copy. The storage
owner is `utils/cwl_dashboard_state.py`; collection alias `cwl_dashboard_state`
defaults to `settings.cwl_dashboard_state` and follows `MONGODB_ROUTES`. Its one
head contains a compressed, checksummed SQL image of **every** dashboard table,
including signups, assignments, publications, bonus draws/delivery reservations,
trial weights and history, sessions, and pending outboxes. These are recovery
images, not a migration to individual Mongo documents per signup. No TTL applies.

For changed transactions, publish the candidate image with majority+journal
acknowledgement and a revision/owner compare-and-set **before** local commit and
before HTTP success. On acknowledgement uncertainty, fence further local reads
and writes; restart and recover Mongo's authoritative result before retrying.
A notification reservation is checkpointed before delivery, so recovery does not
silently retry an uncertain Discord send. A local commit failure also fences the
process. A server crash after Mongo acceptance can preserve a change whose HTTP
response was lost; check the recovered result instead of assuming it failed.

The writer lease is renewed every 20 seconds and expires after 90 seconds.
A second server must wait for a crashed writer's lease to expire; a clean stop
releases it. Revision and owner checks fence the old writer. Use synchronized
system clocks. The local process lock also prevents recovery racing the running
service. Mongo outages fail saves closed; the service logs a critical error and
needs restart after connectivity is restored. Do not bypass this by running
`create_app` directly in production or editing SQLite while the service runs.

### Initial migration

Take a fresh encrypted backup, stop `wu-cwl-demo-web.service`, then run:

```sh
./.venv/bin/python tools/backup/dashboard_recovery.py initialize --env-file .local/cwl-web.env
```

Initialization refuses to overwrite an existing Mongo head, rejects empty or
invalid SQLite, and verifies integrity/foreign keys. Start the service only after
initialization succeeds. Subsequent starts read Mongo first, restore the working
copy, run idempotent schema migrations, and checkpoint them before workers start.
A missing head or unavailable Mongo fails startup; it never creates an empty
replacement roster. The former local database is retained as `.before-mongo`.

### Replacement server and independent recovery verification

Provision the same code/dependencies, private environment (Mongo credentials,
Discord credentials, public origin), and VAPID private key from secure backup.
Set `CWL_WEB_DB_PATH` to a writable local path. Stop the old web service, or wait
for its lease to expire after a crash, then run the production entrypoint. Do
**not** run initialization on the replacement host: startup restores from Mongo.
Keep only one production bot/web deployment active to avoid unrelated bot jobs
running twice. Domain changes also require OAuth callback/DNS updates.

Verify or export without touching the live working database or acquiring its
writer lease:

```sh
./.venv/bin/python tools/backup/dashboard_recovery.py verify --env-file .local/cwl-web.env
./.venv/bin/python tools/backup/dashboard_recovery.py export --env-file .local/cwl-web.env --output /secure/new-recovered.sqlite
```

Export refuses an existing destination. Keep exported files private: they contain
session and subscription data. A Mongo recovery checkpoint is not historical
backup against mistakes/deletions. Existing encrypted Restic/R2 snapshots remain
necessary: SQLite every five minutes, Mongo on its configured timer, and daily
isolated restore verification. Keep the Restic password and service credentials
accessible independently of this server. A simultaneous loss of Mongo and this
host has the off-site backup's recovery window, not a zero-loss guarantee.

Current image safety bounds are 64 MiB uncompressed and 12 MiB compressed; an
oversize image rejects the transaction rather than silently dropping recovery.
The initial live image was approximately 43 KiB compressed (44 tables). Revisit
chunked checkpoint storage before growth approaches the limit.

Validation: isolated rollback, unavailable/ambiguous Mongo, post-Mongo/pre-local
crash, stale writer, active second writer, corrupt image/local file, seed replay,
missing head, and weight/history recovery tests. Real Mongo drill uses an
authenticated temporary loopback server via `CWL_RECOVERY_MONGOD`; it never uses
production credentials. Live source rows were independently round-tripped
read-only. No frontend controls changed; no live notification test is implied.
