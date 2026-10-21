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
