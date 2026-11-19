# Town Halls registry

`utils/town_halls.py` owns the `town_halls` collection, selected through the
`fwa_data` route. One server document uses its decimal guild ID as `_id`, schema
version 1 (244) or 2 (245 bases), a business `revision`, `lowest_fwa_town_hall`, and `levels` keyed by
canonical decimal levels 1–99. There are 1–30 levels. Each level has an optional
Discord custom-emoji markup and optional integer weight pair. Weight ranges must
increase without overlap. The lowest FWA level must exist and have a weight.
Display ranges are computed when read. No ordinary save creates a registry.

The migration sets the lowest FWA level to 12. Weight calculations and the
reference table use weighted levels at or above that setting. Clan minimum-level
choices use every registered level, newest first. Base bank rows/details and native base menus use only registry variants with a
saved link, at or above the minimum. Shared images never make a linkless variant
visible. An app-local generation invalidates completed and in-flight base reads
after a committed minimum or base edit. A superseded read cannot refill the cache;
it retries once within the same eight-second budget, then becomes unavailable.
Existing unknown clan values
can be preserved unchanged; another unknown value cannot be selected and saved.
Family role IDs remain in their existing table until prompt 246.

Dashboard select-option values are strings for the existing HTML controls; the
Lowest FWA Town Hall draft is converted to a canonical integer before Save. The
registry schema and stored minimum remain integers.

The dashboard's Town Halls section uses the existing `fwa_weight` permission for
admin fields and `fwa_bases` for base fields, within the `fwa` scope. Its list, Add, minimum-level, emoji and weight edits require explicit
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

Release order (1179–1184):244 first, ahead of249 and239L;245 after244 is live. Obtain Shaka approval of the current full head; verify backups
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
245's later concurrency distinction. The 244 migration still creates schema 1.

## Bases in schema2 (245)

Each level may have `bases.war_image` and `bases.active_image`, shared by Merged
and Non-merged. `bases.merged` and `bases.non_merged` each hold optional `link`,
`instructions` and `upgrade_notes`. Links are Clash OpenLayout HTTPS URLs; images
use the existing public HTTPS rule. Text is at most 4,000 characters. Below-minimum
base data remains stored but hidden. Base menus keep old `th19`/`th19_new` values,
show linked variants newest-first/Merged-first, and cap at 25 highest choices.

A base-only Save atomically compares each changed field's saved value (or exact
absence) and increments the global revision. It does not use an unrelated emoji
or weight revision as a conflict. `nonbase_revision` records the last global
revision that changed admin-owned values; it is not an independent counter.
Admin saves keep their mutual conflict protection while updating only non-base
paths. A known no-match caused solely by a base revision permits one bounded
reload/CAS attempt; uncertain writes are never retried. A mixed admin/base Save
uses both conditions in one atomic CAS, never sequential partial writes. Same
base field conflicts return “This base changed. Refresh and review your edit.”
History records only the edited fields for a partial level Save; the existing
post-CAS history failure/crash limitation above still applies. Restores are
explicit, permission-checked and compare the reviewed current revision and values.
Raw history preserves missing versus empty fields. Undo removes the highest
originally absent base container or field only when its whole current value still
matches the opposite saved image and every removed leaf belongs to that history
entry. Known or racing neighbor edits conflict; no unrelated field is removed.
The final restored document is validated before the same atomic CAS. A history
entry without raw presence information cannot be restored by guessing empty text.

The existing `fwa_weight` permission owns Add, Lowest, emoji and weight. The
existing `fwa_bases` permission owns shared images and variant fields. Either can
open the section; restricted sections are text, not disabled inputs. Base-only
users have no Add/Other levels controls and see Lowest as text. Upload creates
media under `fwa/bases/th<n>` and changes the draft URL only; it never saves the
registry. Only explicit Save commits it. Old base GET links redirect to Town
Halls, while legacy PATCH/upload endpoints return 410 and cannot write old maps.
Discord edit/upload controls are dashboard link cards; member base menus remain.
The bot snapshot refresh also publishes each shared image under both legacy keys.

Run `tools/migrate_town_halls.py --bases --guild-id <guild> --dry-run` against the
fresh reviewed backup/copy. The separately authorized `--apply` copies legacy
base fields once, bumps schema2, initializes the non-base marker atomically and
never changes `fwa_config`. Merged images win; Non-merged is fallback only when
Merged is absent. The report lists every copied key, both differing image URLs,
below-minimum copied levels and actual/planned counts. Any existing level bases
means already migrated/no write. No data means no write. A failed/uncertain apply
is not retried or repaired automatically. 1182 quotes Ruggie’s “release245”; release
still requires 244 live and Shaka’s approval naming 245’s current full head.

Rollback requires the 1184-compatible 244 code: it reads schema2, preserves bases
and stamps non-base revisions on ordinary admin saves. Its base bank still reads
the unchanged legacy `fwa_config`, so base edits made after 245 release are not
visible after code rollback. Never restore a database to roll back code.
