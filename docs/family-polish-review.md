# Family follow-up162/167

Add clan closes the current editor before navigating to the directory; dirty
changes still require the existing in-app discard confirmation. The FWA impact
warning uses the exact stored FWA type, matching backend consumers, so legacy
Farming does not falsely claim FWA effects. Disabled reminder summaries explicitly
say the times are saved. History labels failed/unconfirmed reminder writes
"Not confirmed", since a timeout may occur after the database accepted the write.
No automatic retry or new write behavior was added.

Regressions cover route/editor agreement, exact-FWA warning, singular/plural
reminder summaries, endpoint confirmation labels, real nested snapshot field
matching, and Discord mention formatting with escaped external text and mentions
disabled. Five mutations (plural, exact-FWA, endpoint label, snapshot path and
show_clan formatter) were killed. Focused backend33 and frontend14 pass; full
frontend1110 passed, and final TypeScript/build passed. Full backend and isolated
320/360/390/1440 browser checks are recorded in the handoff before READY.

No production or live Discord testing is part of these checks. Existing artwork,
reminder CAS, permission, data-retention and delivery behavior remains unchanged.
