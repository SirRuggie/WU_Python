# Strikes identity recovery

The identity cache waited120 seconds after a failure, but the page stopped after
six short polls or a completed failed task. An open page could therefore keep
zero names indefinitely. The whole background refresh also had only8 seconds
for sequential link batches and the complete Discord directory. Initial loading
was presented as an error.

The page now retries failed/pending identity reads at a bounded two-minute pace
after its initial six short polls, pauses while hidden/busy, stops on permission
loss and ignores superseded results. The background job has110 seconds; this
bounds six15-second provider batches and leaves directory time without blocking
the HTTP page response. IDs survive a directory failure, and prior names survive
only when the confirmed owner ID is unchanged. Failures log type/count/elapsed,
without member names or credentials. A muted line appears for an actual failure;
an initial pending read has no unavailable warning.

Isolated checks:27 Strikes HTTP/activity tests, including an8.05-second successful
lookup and failure-cooldown recovery;1285frontend tests/233files,tsc/build,
16width/population layout combinations, and both behavioral mutants killed
(eight-second budget and stopped retry). No mocked test proves live upstream
availability. Runtime source establishes the retry gap; live provider timing was
not sampled because automatic approval review rejected exporting production tags
for that optional probe. Shared/tmp inode exhaustion was independently relieved
from100% to78% by deleting completed release dependency folders, preserving
Claude's review dependencies, evidence, backups and rollback assets.

No database migration or bot restart. Release after Claude ACCEPT uses a clean
tagged backend/frontend build, fresh backup/testrestore and protected-state,
readiness, journal, public asset and rollback gates. Claude rechecks real names.
