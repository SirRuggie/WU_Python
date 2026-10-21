# Member season and clean links — 2026-10-21

Members use `/signup`, `/assignments`, `/tasks`, `/wars`, `/events`, `/search`
and `/`. Season IDs are retained only on CWL staff pages. Legacy query links
remain accepted, but member pages always resolve the season chosen by staff.
OAuth uses an allowlist of local paths, preserves the signup destination across
sign-in/retry, and ignores legacy season IDs. Announcement signup buttons use
https://cwl.ruggie.zone/signup. CWL settings includes a copyable direct link.

## Selection and access

CWL settings → Season settings → Season shown to members controls the selection.
Creating a subsequent draft never changes it. Staff can hide the member season.
Closing signups preserves member access to saved signups and published assignments.
Archiving the selected season also preserves read-only visibility until staff
switches or hides it; archived seasons cannot be newly selected. Staff retain
access to historical seasons. Personal pages use the member season even for staff,
while staff workspace selection is kept separately.

All season-specific member API requests check the chosen season, including reads,
new signups and withdrawals. Members receive only that season in the season list.
A stale hidden-season write is rejected rather than silently applied to a new
season. The visible season refreshes on focus and every minute while visible;
season changes reset unfinished signup selections. Existing request identity and
season guards reject stale account responses. Selection writes use a revision,
CSRF and CWL staff authorization and retain an audit entry.

## Storage migration

One additive singleton `member_season` table is owned by `cwl_web.store.Store`.
On initial migration it pins the latest non-archived season once, preserving the
previous default for existing active installations. Empty databases select their
first created season. Subsequent creation and restarts do not override the choice
or a deliberate hidden state. No signup, publication or roster data is rewritten.

## Review evidence

- 567 CWL pytest cases passed before the final added migration test; the final
  targeted season/announcement suite passed 6 tests, including that migration.
- 192 frontend tests passed, including clean paths, legacy links, safe OAuth
  destinations, staff season links and cancelable Back/Forward navigation.
- War reminder gate and production build passed. Existing bundle-size and aiohttp
  deprecation warnings remain.
- Exercised CSRF, member/staff authorization, malformed and oversized IDs,
  conflicting selection revisions, hidden-season reads/writes, archive behavior,
  explicit hiding, future drafts, restart persistence and one-time migration.
- Isolated browser: direct signup load, Tasks navigation, Back, staff draft
  creation, explicit season switch, old season link normalization, copy link,
  logged-out signup destination and fixture sign-in. Inspected 320px, 390px and
  1440px; the 320px staff page had no horizontal overflow. Native controls and
  status feedback were retained. No real signups or live messages used for QA.

Spreadsheet/weight source changes remain deferred.
