# Family clans redesign — implementation record

This batch is in progress on `codex/family-clans-2` from `b611af4`. It is not
released or ready for review. The approved specification is handoff prompt 29,
with the all-stored-types decision in Claude entry 117 replacing item 11.

## Directory findings and changes

The live provider used a four-type allowlist (FWA, Tactical, Flexible Fun,
Competitive), excluding CWL, CWL Hosting, Unknown and other stored categories.
The same allowlist appeared in member classification, web return choices and
the Discord Main return selector. The provider feeds the approved-host choices,
signup family status and roster outside-family status, including background
metadata refresh. Those consumers already use directory membership rather
than their own type filters.

Family reads now accept active stored clans regardless of type. Removed clans
are normally deleted from the collection; explicit removed/archived flags are
also excluded. FWA signup restrictions and FWA return scheduling retain their
separate exact-FWA checks. No saved clan type, signup, assignment or lock is
rewritten. The return UI continues separating Main and FWA destinations while
including previously excluded categories in Main.

Checks so far: 5,024 backend tests passed (21 skipped, 162 subtests), including
stored Unknown/CWL Hosting membership, unstored outside status, removed/archived
exclusion, unchanged FWA rules and expanded return choices. Restoring the member
type allowlist fails three new tests. These tests use isolated databases and
fake upstream data; they do not prove live delivery. Per-pool outside-count
fixture evidence is still required before review.

## Reminder editor work

Configured quick-add times are hidden, with explicit add/remove controls kept.
The reminder picker shows channel names and an unavailable label instead of raw
IDs. Delivery outcomes use an icon and capitalized word; skip reasons remain
visible without inventing a late-delivery reason. Receipt links use scoped app
styling and visible focus.

Send test first opens the existing in-app confirmation naming the channel.
Cancel sends nothing. Confirmation refuses a changed payload or destination,
and an uncertain delivery retains its existing receipt identity. There is no
automatic retry. An unavailable channel name disables the test action.

Copy changes so far:

| Before | After |
| --- | --- |
| Who needs a reminder? | Remind who? |
| Players with any attacks remaining | Players with attacks left |
| selected reminder channel name and ID | channel name only |
| Channel ID (unavailable) | Selected channel unavailable |
| sent / failed / skipped / uncertain | ✓ Sent / ! Failed / – Skipped / ? Uncertain |

The larger navigation, combined-save, history/copy, add/restore, artwork and
legacy Discord-handler changes remain in progress. Narrow/wide browser checks,
full final regression/build, required mutation set and completion review remain
mandatory before READY. No production settings or Discord messages were changed
by this development work.

## Combined editor progress (not final verification)

The clan editor now has one Save/Discard bar for clan fields and reminder settings.
Each API receives its own saved revision. Render tests cover either section
conflicting while the other saves, retention of the failed draft, and in-app
confirmation before leaving or removing a named clan. Phone section cards retain
their drafts when collapsed; hidden reminder sections stop polling and previews.
The phone directory is hidden while a clan is open. Off reminder rows are compact;
rows with attention errors retain their details and remain first.

Validation: 1,075 frontend tests passed across 207 files, including the new
combined-editor, hidden-polling and compact-overview regressions. TypeScript passed.
Mutating the default to Reminders and restoring a second save bar each killed the
new render tests. Browser measurements, routing, and the remaining prompt items
still require implementation and final verification; these checks are not a
READY declaration.

Additional copy: `Latest scheduled outcome` → `Last reminder`; the old separate
`Save reminders` control is replaced by the shared `Save` in the clan editor.

Role controls now share the Strike settings searchable picker, preserving server
order and color metadata while excluding managed roles from new selections.
Existing selected roles remain visible, including unavailable roles. Clan leaders
show their name and avatar; an unavailable leader no longer prints the raw ID.
The existing public member-option helper provides avatar URLs. Backend role and
selected-member regressions pass (8 clan API tests); 32 focused frontend tests
cover the shared picker, clan fields, combined editor and choice loading.

Claude entry148 cancels the Clan Games ClashKing switch per Ruggie. Remaining
batch order after Family clans is31 then19; the current ClashPerk source stays.

Role increment validation completed: 1,076 frontend tests / 208 files, TypeScript
and build passed. Restoring the raw leader-ID fallback killed the ClanFields
render test; restored test passed. Full-batch backend/browser checks remain pending.

## Route checkpoint

Family clan tabs, selected tags and sections now round-trip through dashboard
paths and the existing DashboardHistory controller. Reload routes serve the SPA
only for valid clan tags/sections, preserving Strikes and Replacements routes.
The clan page restores a shared section link after loading its directory. Leaving
unsaved clan changes through dashboard navigation uses ConfirmDialog; writes in
progress block navigation. A history replay that produces no popstate does not
clear the dirty guard (App regression).

Route checks: 26 targeted frontend tests plus the App guard regression passed;
full frontend 1,079 tests / 209 files passed. Five isolated backend route tests
with 55 subtests passed. Final real-browser Back/Forward and layout checks remain
part of the batch completion gate.

## Completion checkpoint (shared layout gate still pending)

History now renders confirmed field changes with frozen available Discord names,
relative/exact timestamps and day grouping. Reminder changes carry a durable
before-image and confirmed diff, including channel names on direct edits. Older
snapshots remain explicitly labeled; absent historical names are never guessed.
Reminder copy preserves each destination's channel and revision, reports partial
results, and retains delivery receipts. Add first looks up a public clan roster;
existing clans open, removed clans offer confirmed restore or fresh setup. Fresh
setup clears reminder settings with their own captured revision; a concurrent
change is retained and reported as a partial result. The checklist appears in the
add flow, rather than duplicating navigation on every existing clan page.

Usage links use active season lineup records and exact FWA membership, and open
separately to preserve the current draft. Confirmed artwork replacements record
cleanup work in the existing history owner. The backend retries owned,
content-addressed clan-image deletion every five minutes, preserving currently
referenced clan images and skipping foreign/static/FWA objects. Failed deletes
remain pending across restarts. No images or Discord messages were changed by
these mocked tests. If secondary history completion is unavailable, the save still
succeeds and retains its before-image; cleanup is not falsely reported complete.

Additional copy changes:

| Before | After |
| --- | --- |
| Reminder overview / Settings history | Reminders / History |
| Monitor your family's reminders and manage each clan in one place | Set up each clan and its war reminders. |
| Not configured | Off |
| Tracking battle day | War is on. Reminders are active. |
| Settings saved before edit | Before this change |
| Removal snapshots | Removed clans |
| Each entry is a copy saved before an edit or removal… | Confirmed changes show what changed; older entries show saved settings. |
| Add clan (immediate submission) | Look up clan → Found: name · member count → Add |
| Clan added. Select it to finish its settings. | Review the setup checklist for this clan. |
| silent existing-tag add | Already in the family · Open |
| Build roster: Clan settings | Hosting clans |
| Set in Clan settings / Set capacity in Clan settings first | Set in Hosting clans / Set capacity in Hosting clans first |

Isolated browser fixture: 25 clans, 2 enabled and 23 off; 320, 360, 390 and
1440px. No horizontal overflow; controls including checkbox labels have 44px
height and at least 12px text. Clean Back/Forward works, dirty Back cancellation
retains the edit, and both Remove and Send test confirmations cancel without a
management write. The fixture's preview response is synthetic and cannot prove
Discord delivery. The overview measures 4.02 screens at 360×800, compared with
the audit's 14.1-screen prior layout (different synthetic data, not a production
before/after benchmark). Screenshots and metrics: `/tmp/wu-family-layout/`.

The per-pool classification regression shows Main outside 1→0 and Lazy outside
1→0 when CWL/Unknown stored clans join the directory, with pools, assignments and
locks unchanged. FWA-specific policy stays separate and covered by regressions.

Mutations killed across the batch: default Reminders tab, native confirm, Send
test without confirmation, raw leader ID, duplicate save bar, restored legacy
write, copied channel, skipped copy revision, silent existing add, fresh setup
retaining reminders, missing type warning, and keeping replaced artwork.

Latest completed backend full run: 5,081 passed / 21 skipped / 162 subtests;
latest frontend full run: 1,097 passed / 213 files; tsc/build and the war-reminder
gate passed. A further backend run covers the final channel-history change.
The shared `npm run test:layout` hit a timeout at
`signup-card.browser.cjs:72` waiting for `.member-signup-success`. This blocks
READY; the affected signup source/test/fixture are unchanged from the branch
base. Do not treat the successful Family-specific browser checks as a substitute
for resolving that shared gate. No deployment is authorized by this checkpoint.

Current queue per Claude 149–150: Family 29 → Announcements with images 45 →
carousel 44 → triggers 31 → 19. Clan Games remains on ClashPerk.
