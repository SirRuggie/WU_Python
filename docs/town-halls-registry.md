# Town Halls registry

`utils/town_halls.py` owns the `town_halls` collection, selected through the
`fwa_data` route. One server document uses its decimal guild ID as `_id`, schema
version 1, a business `revision`, `lowest_fwa_town_hall`, and `levels` keyed by
canonical decimal levels 1–99. There are 1–30 levels. Each level has an optional
Discord custom-emoji markup and optional integer weight pair. Weight ranges must
increase without overlap. The lowest FWA level must exist and have a weight.
Display ranges are computed when read. No ordinary save creates a registry.

The migration sets the lowest FWA level to 12. Weight calculations and the
reference table use weighted levels at or above that setting. Clan minimum-level
choices use every registered level, newest first. Base bank rows/details and
native base-section choices filter the existing legacy base dataset by the same
minimum. After an explicit minimum Save, an app-local generation invalidates
both completed and in-flight base reads. A superseded read cannot refill the
cache; it retries once within the same eight-second budget, then returns an
unavailable response if settings keep changing. This visibility change does not
migrate or rewrite base content. Existing unknown clan values
can be preserved unchanged; another unknown value cannot be selected and saved.
Family role IDs remain in their existing table until prompt 246.

Dashboard select-option values are strings for the existing HTML controls; the
Lowest FWA Town Hall draft is converted to a canonical integer before Save. The
registry schema and stored minimum remain integers.

The dashboard's Town Halls section uses the existing `fwa_weight` permission and
`fwa` scope. Its list, Add, minimum-level, emoji and weight edits require explicit
Save. A stale revision returns 409 without a registry, history or refresh-request
write. The old weight PATCH route returns 410. Discord's former weight editors
and old controls show a private dashboard link card and cannot write settings.

## Snapshot and refresh

Synchronous Discord rendering reads a single last-good process snapshot through
`town_hall_emoji`. No configured emoji returns an empty string; text callers retain
the level label and select options omit the emoji. Startup loads the registry next
to the FWA image cache and logs one ERROR if it cannot load. The management worker
attempts refresh every five minutes, keeping the previous snapshot and logging one
WARNING per failed attempt. Failures are throttled too.

After a successful dashboard Save, the HTTP adapter queues an existing durable
`manage_web_request` for `town_halls/refresh`, deduplicated by server and saved
revision. The bot rechecks permission, guild, action and the revision on the exact
snapshot load before publishing it. This request reads the registry only: it sends
no Discord messages and changes no registry business data. Queue processing has
the existing worker cadence; it is not an instantaneous cross-process update. A
queue failure never retries Save or claims the committed edit was unsaved. The
five-minute refresh remains the recovery path.

## Change-history limit

After a successful registry CAS, the existing change-history owner attempts one
saved entry with ID `dashboard-history:town-halls:<guild>:<revision>`, retaining the
before-values read at the expected revision and the edit/restore attribution.
A duplicate ID counts as already recorded. If insertion fails or times out, Save
still succeeds with `history_saved: false`; one WARNING includes the saved
revision. There is no automatic data-write retry or history replay worker.

**A process crash between the registry CAS and history insertion can lose one
history entry.** The registry edit itself remains safe and revision checked.
Registry and history writes are not atomic, and the UI cannot display a warning
if the process crashes before returning its response. This is the explicitly
accepted Shaka 1178 limitation; do not describe history as guaranteed for every
failure. No pending-history field, outbox, backlog cap or compensating delete is
introduced.

## Migration and release

`tools/migrate_town_halls.py --guild-id <guild> --dry-run` is the default; an
optional `--report .local/<report>.json` writes the review report. The tool's
internal seed table is the only retained copy of the former code emoji map.
It copies existing weight min/max pairs, preserves full-markup overrides, reports
name-only overrides for manual review, and seeds other levels through at least
TH19. Missing TH12 weight stops the migration. The legacy `war_weight_settings`
document is never changed or deleted. Typed BSON digests and collection counts
are checked before and after. A second apply to an existing registry writes
nothing and reports already migrated.

Release order: finish 239L; obtain the task's normal code approval; verify backups
and protected counts; run production dry-run; show its report to Ruggie; run
`--apply` only after Ruggie's own migration authorization and “release 244” are
quoted in the handoff thread; verify one registry document and byte-identical
legacy weights; then follow the documented backend, bot and frontend switches.
Development tests and previews use isolated fixtures only. No production
migration or release is implied by these instructions.

Code rollback reads the untouched legacy weight record and old code emoji maps.
Registry edits made after release will therefore be absent from old code after a
rollback. Never restore a database to roll back code. Base sections/storage move
in prompt 245; the family role mapping moves in prompt 246.

Add history is recorded as `create`. Its before-side is not restorable: creation
does not authorize deletion of a level. The saved after-side and ordinary
level/settings edits retain the existing revision-checked restore behavior.

244 rollback compatibility (1184): schema2 base fields may be read and copied
unchanged by this release. No base editor or base-writing action is added here.
An emoji/weight/minimum Save keeps the existing global revision CAS and stamps
`nonbase_revision` with the new global revision on schema2 documents, preserving
245's later concurrency distinction. The244 migration still creates schema1.
