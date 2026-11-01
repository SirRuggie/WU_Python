
Prompt 67 Stop checkpoint: a durable stop_requested barrier holds the existing
single queued lane while a claimed member finishes, cancels unclaimed pending
members, then marks the parent stopped. Deterministic confirmation replay returns
the same stopped run; it cannot resume. Worker transport checks the parent barrier
before a new nickname operation. Named manifest results retain unselected/skipped
members and their reasons. Stop uses the same member_roles scope and run owner /
guild binding as status; no agent-run production Standardize was performed.
Targeted checks: 22 backend, six component cases, six actual isolated Mongo cases,
tsc/build. The first new Mongo scenario used 1970 timestamps and correctly hit
retention; it was corrected to a realistic clock before the six-case passing run.
This is an increment, not READY: compact top-action/paged UI, conflict/retry work,
pace documentation and complete final regression/layout/mutation gates remain.
