# Roster account actions

Add Unassign from clan before Remove signup in account Details. Reuse the existing
confirmation dialog, with Cancel initially focused and an explicitly named action.
Unassign uses the existing revision-checked roster edit and clears only clan and
placement lock; signup and saved weight remain. Remove retains the existing signup
endpoint. Neither changes published rosters until staff publishes again.

Keep roster and signup permissions independent. Archived seasons, busy mutations,
unsaved edits and pool reviews block conflicting actions. Already-unassigned rows
show a disabled action with an explanation. Failed actions preserve the editor,
show the existing error area and restore focus to the triggering action.

Sol reviewed permission boundaries, payload preservation, confirmation/cancellation,
duplicate submissions and failure flow. Its focus-restoration finding was fixed.
Isolated browser used only fictional data: desktop action order, cancel with focus
return and no change, confirmed unassign payload (null clan, false lock), preserved
weight, disabled already-unassigned action, remove popup and failed remove with
editor/focus retained. At 320px the popup and editor reflow without horizontal
scroll. No live account was unassigned or removed during testing.

Full frontend suite (396 tests), TypeScript and isolated Vite build passed.
Existing roster/balance backend regression suites checked; no backend or storage
change, migration, signup deletion or live notification is part of this release.
