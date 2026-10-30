# Official clan weights

Clan management → Clan weights is the authoritative saved weight ledger for
family FWA accounts, keyed by player tag. Current membership comes from Clash;
saved weights survive clan moves and restarts. The searchable clan selector,
war-order rows, storage/loot/full-weight editor, and Column F copy remain available.

`utils/clan_weight_store.py` owns `clan_player_weights` and
`clan_player_weight_history`. The October 22 migration renames the previous trial
tables in place, preserving every value, revision and audit record. No parallel
test copy is created. Writes use the dashboard Store transaction and majority-
acknowledged Mongo recovery checkpoints. Legacy HTTP paths and internal app keys
remain compatible with existing clients; they do not select a separate database.

The roster popup and Clan weights now edit one linked ledger, including FWA
players. Full input accepts `179000`, `179,000` and `179k`; Loot × storages uses
the same parser. Clear is local until explicit Save. A saved blank means Not
Available and never revives an older imported value. Popup creation requires a
signup in the selected season; Find any player still cannot create a never-saved
random tag. Popup and queue weight writes require both roster editing access and
Clan weights access (or owner); placement-only edits still require roster access
alone. Roster-only staff see a read-only weight and the Clan weights reference.
The HTTP route enforces the weight permission before any database mutation.
Historical non-thousand values remain readable; opening their editor is clean,
and entering a replacement uses the shared parser without rounding.

Legacy manual and clan values are resolved by timezone-aware saved instant;
equal instants favor the clan ledger. No legacy rows/events are deleted or
rewritten. The October 30 read-only backup audit found 42 legacy rows and 350
clan rows, no missing/naive timestamps, zero overlaps and zero effective-weight
changes. The season-scope audit of the 19:19Z release backup covered every
season: one draft season, 155 signups, two publications, zero effective changes;
there were no archived seasons. Published snapshot rows are not rewritten.
Repeat both audits from the fresh release backup at activation, and stop if an
archived or published season changes.

Both edit paths record actor, aware time and source (`Roster` / `Clan weights`)
in clan history and use the same per-player revision. A conflicting changed
value gets `Changed by someone else · Reload`; the popup retains typed input
until explicit Reload and a subsequent Save. Identical-value replay retains the
existing idempotent no-op behavior. Draft roster invalidation remains shared
across seasons containing the player; published snapshots remain immutable.
Placement Undo changes only assignment/lock, never the linked weight. The roster
revision gate remains mandatory, and prior placement receipts become stale after
a weight change. Legacy manual rows remain available for code rollback.

Saves recheck that the clan is still in the family and the edited accounts are
still current members. Per-player revisions reject conflicting edits atomically.
Replaying an already accepted value does not duplicate history. Different
players can be updated independently. Membership can still change immediately
after a Clash API response; a later refresh reflects that upstream change.

Export & copy is collapsed by default. Native XLSX exports all saved trial
records, including departed players, with full and shorthand numeric weights.
Clan metadata is explicitly labeled "at last save", not current membership.
Excel string cells cannot execute external names as formulas; invalid XML
control characters are removed. Copy current clan uses TSV with formula-safe
names. Export/copy requires saved changes. Openpyxl is the sole new dependency.

## Verification — 2026-10-21

570 backend tests and 196 frontend tests passed, along with the war-reminder
gate and production build. Tests cover authorization/CSRF, explicit clan grants,
malformed weights/revisions, family ownership, membership loss, all-or-none
writes, concurrent conflicting edits, idempotent replay, restarts, player moves,
clearing weights, upstream failure, XLSX numeric/string types and live-weight
isolation. Navigation rendering has a regression for the new sidebar entry.

Isolated 50-player browser checks covered multi-row paste, Enter focus movement,
saving, XLSX download feedback and 320px/390px/desktop layouts. The 320px page
has no horizontal overflow. No live weights or Discord messages used for QA.
Existing build-size and aiohttp deprecation warnings remain.

## Referenced calculator (read-only investigation)

In the linked Simple Weight workbook, English!C3 contains Edrag Rush.
English!G3 is a lookup formula using that name and subCheckSheet; overwriting it
would destroy the lookup. The member area refers to CurrentWar, and the sheet
instructs users to invoke Calculate to load war data. That is distinct from
current clan membership. No sheet data/formula/script was changed. Google Sheets
API edits do not invoke Apps Script edit triggers; automated calculation would
require a supported script entry point or the existing UI operation, not simply
a tag-cell write. The requested primary weight spreadsheet integration remains
deferred.

## Storage and loot editor (October 21)

The trial now stores a nullable storage count alongside each player's full integer
weight, with an additive column on both trial tables. Existing weights remain
unchanged. Unset counts display a starting value of five (four for TH8 and below);
counts are editable from one to five and must be checked against the destination
sheet. Loot is derived from full weight / storages. Editing loot or storages
recomputes full weight; editing full weight recomputes loot. Fractional or
inconsistent results cannot be saved. Both fields blank means Not Available.
There is no separate small-storage adjustment in this trial.

Clan position comes from the live member list, while optional war position comes
from a validated current-war lineup. Private/unavailable war data never hides
current members. The FWA copy contains one numeric loot column in war map order,
with no header, ready for F17; unknown lineup, missing current members or missing
weights blocks it. Users must verify the same clan/war and storage counts, and
ensure the sheet has no extra small-storage adjustment, before pasting. Copying
never submits to FWA. The full table and saved Excel export remain available.

A searchable disclosure replaces the large clan sidebar on all widths. Enter
moves down the same field; Tab moves across fields. Unsaved navigation guards,
revision conflicts and membership revalidation remain in effect. All data stays
isolated from live CWL weights and no Google Sheets connection was added.

Validation for this revision: four backend trial tests cover authorization/CSRF,
malformed values, removed members, revision conflicts, replay, restart persistence,
formula-safe exports and optional/malformed war data. Frontend tests cover both
calculation directions, invalid/fractional values, atomic column paste and safe
war-order copying. The full frontend suite and production build passed, as did
the war-reminder regression gate. Isolated 50-member browser checks covered
substring clan search, focus restoration, calculation/save/reload, blocked copying
with missing loot, and desktop/390px/320px layouts without page overflow. Errors
receive focus so failed copying at the bottom is discoverable. No live Sheets,
FWA submission, or Discord delivery was performed. Existing build-size and aiohttp
warnings remain. This is not an exhaustive assistive-technology audit.

War-order follow-up: current preparation/battle lineups and the last completed
lineup returned by Clash use map position order. The # column shows plain bold
numbers. Current members outside that war follow in a separate section with no
war position. If Clash cannot provide a lineup, the editor explicitly labels its
clan-order fallback; it does not invent historical war placements. Saving retains
the displayed lineup metadata. Five backend tests and 197 frontend tests passed,
along with the production build and war-reminder gate.

The clan directory and member read/save routes now include only family clans
whose stored category is FWA. Other categories and missing categories are
excluded; reclassification blocks stale editor saves without deleting stored
player weights. Six feature tests cover the filter, direct non-FWA access and
reclassification. This changes the existing selector's data only; no controls,
layout or keyboard behavior changed.

Inline destination-sheet checks are advisory: full weights must end in 000 and
fall between 42,000 and 180,000 inclusive. A valid weight higher than the preceding
actual war position gets a double-check warning. Missing, invalid, unavailable or
non-adjacent war rows are not used for comparisons. These mirror the inspected
FWA sheet, not independently verified FWA policy; the editor still supports its
existing save/copy behavior and numeric validation. No data migration or saved
weight writes occur. Warnings are derived from current drafts, associated with
inputs by aria-describedby, and use text as well as color. Checks covered limit
boundaries, invalid/blank drafts, war gaps, non-war members, live correction and
390px/desktop reflow with isolated data. All 199 frontend tests, production build
and the war-reminder gate passed. No live clan weights were edited during QA.

The C–H copy experiment was removed because SimpleSheet protects its derived
columns. Column F remains the supported FWA paste format. Saved weights and the
existing general table/Excel exports are unchanged. Removal validation: frontend
regressions, production build, and war-reminder gate.

Each selected clan displays its last actual weight save time (viewer-local) and
Discord actor beneath the member-refresh timestamp. The history storage owner
supplies the receipt, indexed by clan and history id. An additive nullable
actor_name column preserves the session display name on new saves; old receipts
resolve from existing session names, otherwise show an explicit Discord ID or
unknown-user fallback. Spreadsheet imports are labeled. No existing weights,
revisions or history timestamps are rewritten. Empty, replayed, or rolled-back
saves do not advance the receipt; departed members do not erase it. Eight backend
feature tests, 199 frontend tests, build and war-reminder gate passed. Isolated
browser checks verified the new status updates after saving and mobile reflow.

## Official ledger reconciliation — October 22

Compared WU FWA War Weights, tab WU FWA Clans, A6:BG66 against current official
membership for all seven FWA clans. Names were matched uniquely inside each clan;
duplicate ANTONY+ accounts were distinguished by their current preparation-war
positions (24 and 33). 348 current members matched; eight Wonder Wall values
needed correction. Lil Ace in Four and Twenty and DragonSlayer-12 in Wonder Wall
have no matching sheet row and retain their existing weights at the owner's
explicit request. No sheet cells are edited; this is a one-time reconciliation,
not a recurring spreadsheet dependency.

The deployment rechecks current membership, saved values, and per-player revisions
before applying changes through the official storage owner with Mongo durability.
All preexisting rows/history are retained. Only actual changes add history and
advance last-saved receipts. The source sheet was reread before deployment and
unchanged. The two unmatched records are verified unchanged after the write.

Validation: 363 backend tests passed (one opt-in live test skipped), 221 frontend
tests passed, and the war-reminder validation gate/build passed. Migration tests
verify in-place history preservation, idempotent startup, and revision invalidation;
Mongo recovery tests verify the canonical tables restore on a replacement host.
Priority tests cover saved values, intentional blanks, cached account overlays,
external fallback for unmanaged accounts, and rejected roster overrides. Isolated
desktop/390px UI confirms managed accounts show the authoritative weight and direct
staff to Clan weights without presenting an ineffective manual override.

## Clan weights workflow (prompt21)

The landing list shows cached current-member progress and last-save dates, with
missing clans first. Unknown membership is not zero membership; a failed refresh
retains its previous count with a plain “members checked” timestamp. A bounded background
worker refreshes roster observations alongside lineup capture. Opening the list
does not fan out to game roster endpoints.

Inside a clan, All/Missing/Check filters and Next missing keep the measurement task
focused. A previously saved NULL is intentional Not Available and counts weighed;
an untouched blank with revision zero remains missing. There is no new Not
Available control. Loot absence can still block Column F even on a weighed row.
Phones show Loot beside read-only Full and a storage-count picker; desktop Full
remains editable. Decimal-k entry scales digit strings exactly (the fractional part
is padded to three digits), never multiplies a floating-point decimal. Thus
`32.2k`, `32.20k`, `32,200` and `32200` all mean exactly 32,200. Nonzero digits
beyond three decimal-k places, fractions of a unit, and out-of-range values are rejected. Invalid
values remain visible with correction guidance; full weights must end in 000.
Existing saved values are read unchanged, and unchanged retries do not rewrite
history. The verified backup snapshot had 350 rows, zero nondivisible weights and
zero saved NULL values; that is not a claim about current production data.

Find any player searches saved names/tags literally, including departed players.
Only this explicit saved-player endpoint can update a saved row without current
FWA membership. It cannot create a row for a never-saved tag. Saves retain original
saved-clan provenance and atomically update history, revision and draft-season
invalidation. Unknown current location is shown separately from verified nonfamily
membership. Build roster links managed and current-FWA accounts to this editor;
manual override remains blocked for managed rows.

Old captured lineups contain positions without names. New captures optionally
include names for departed-slot placeholders. Gaps have no controls and never
count toward missing/weighed. Copy still refuses shifted or incomplete war data.
The export checklist checks saved/loot/lineup state; matching the actual sheet war,
storage counts and small-storage adjustment remains a user check.

Local and App navigation use the existing in-app confirmation dialog. Keep editing
retains drafts; Discard performs the requested navigation once. Encoded player/clan
links persist through history and validated OAuth return paths. Access and CSRF
checks remain unchanged. Frontend automated tests cover these interactions;
independent 50-member narrow/wide browser measurements and release evidence are
separate gates, not implied by a local test or build.

## Linked-weight reader audit — October 30 rework

- Bot replacements: `_manual_weights()` now calls the shared resolver, retaining
  explicit nulls so Clear overrides the cached upstream value.
- Dashboard replacements and strikes FWA weights: `source_weights` and
  `overlay_accounts` use the resolver; the retained manual fallback cannot
  override a resolved row, including null.
- Roster, Compare, working exports and publishing input: `_roster_rows` uses
  resolved values. Published exports read immutable publication accounts.
- Clan weight saved-player search and XLSX: `ClanWeightStore` resolves reads.
- Signup carry-forward trigger and recovery migration retain legacy reads solely
  for initial values/history; they do not override effective display values.
- `initial_manual_weight` is intentionally the first historical value, not a
  competing current-weight reader. No legacy records are removed or rewritten.

Rework verification: 4,995 backend tests passed (21 skipped, 162 subtests),
1,042 frontend tests passed, and TypeScript/build passed. Six mutations were
killed: oldest wins, popup legacy-only write, popup CAS bypass, bot legacy-only
read, comparing unchanged values against the linked row rather than the
resolved value, and bypassing the weight permission. Isolated browser checks
at 360 and 1440 covered Save/Clear, conflict/explicit Reload, read-only
roster-only access and closing a historical 151,500 value without a discard
prompt. Targets are at least 44px and there is no horizontal overflow. This
is fixture evidence, not live Discord delivery evidence.

## Linked-weight fault isolation and Clear feedback — October 30

The bot's saved-weight reader isolates an invalid timestamp to its affected player
and logs that tag. Other valid legacy and linked values, including an intentional
linked null, remain available. The ordinary bulk read is unchanged; per-player
resolution runs only after a timestamp error. The affected player's ambiguous
saved value is omitted rather than guessing which ledger wins. This does not
change the shared resolver's strict timestamp validation or write any records.
When the linked table is absent, legacy null rows are excluded again.

An explicitly cleared weight now says `Will clear on Save` in the existing live
hint. Opening a historical non-thousand value remains clean; Clear alone does not
write, and the existing Save, revision conflict and authorization controls remain.

Review covered invalid timestamp isolation alongside valid legacy/linked values
and null semantics, missing-table compatibility, explicit Clear and Save, and
roster-only access. Isolated 360px and 1440px browser checks verified the status,
permission notice and no horizontal overflow. The fixture's optional Discord
member lookup remains unavailable (503); these checks do not establish live
Discord identity or notification delivery. Full-suite and mutation results are
recorded with the review handoff, not treated as production deployment evidence.
