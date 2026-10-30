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
