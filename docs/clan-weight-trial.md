# Clan weights temporary trial

Clan management → Weights · Test is a separate experiment, available to the
owner and staff with the Clan management grant. It uses the existing family
clan directory and public live `clan_roster` provider, not CWL signup/publication
snapshots. Current membership is fetched on selection, refresh and save. It is
not continuously polled while staff are typing. Unavailable or incomplete
upstream membership cannot be treated as a successful empty roster or saved.

Each compact row shows Town Hall, player name/tag and weight in thousands.
Enter/Tab moves between inputs; a single Excel column can be pasted down the
currently displayed rows. The order is TH descending, then name/tag; pasted rows
must follow that displayed order. Save weights commits the changed rows together.
Blank means Not Available; only whole thousands between 1k and 999k are accepted.
There is no automatic save. Unsaved changes are protected on clan changes,
refresh, navigation and browser unload. Mobile uses a native clan selector.

## Isolation and persistence

`utils.clan_weight_trial_store.py` owns additive `clan_weight_trial` and
`clan_weight_trial_history` tables in the dashboard SQLite database. Player tag
is the identity, so saved weights survive leaving/joining clans and restarts.
There is no expiry and no change to live `player_weights`, roster entries,
Google Sheets, external FWA weights or bot calculations. Normal dashboard
database backups must include these tables. This trial has no Mongo outbox.

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
