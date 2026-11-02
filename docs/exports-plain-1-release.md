# Exports plain-language release

Tag `exports-plain-1` identifies merged PR167,
`05570864d3c7991c024f6c58f80659043e31c416`. Its frontend source is identical to
reviewed `1023b99474a1612c8ad367e10baabb2f6df85f4b`. Backend runtime remains
identical to deployed f56; the bot remains 343. Claude 406 accepted the change,
and 423 authorized release after the Members timing health smoke under owner 395.

The page uses plain preview headings, readable values and direct export links,
retains successful preview data on a failed refresh, and clears data on lost
permission. Eight fixture CSV variants remained byte-identical; no backend or
CSV transport change is included. The accepted source passed 1498 frontend tests
in 263 files, 25 focused checks, TypeScript/build, three genuine mutants and
narrow/wide browser checks. The clean tagged checkout was built by the external
immutable frontend stage helper; workspace dist is not a deployment target.

## Staging and guard audit

The helper initially lacked an executable bit and was invoked through Python.
That attempt stopped before output because the clean checkout had no tsc.
Lockfile-pinned npm ci then completed and the immutable build passed. These
failures changed no service or production frontend.

The first fresh gates after an ordinary capture passed backup/test restore and
protected-state checks, then stopped because the canonical head changed between
read-only recovery snapshots. No switch, restart or database restore occurred.
Evidence is retained in the release folder's attempt1-canonical-race directory.
A single retry after the next ordinary capture passed every gate with unchanged guards.

The frontend-only coordinator checks the bot and backend invocation remain
exactly unchanged, atomically switches the external current symlink, verifies
public entry and affected feature hashes, and rolls back only the frontend on
failure. Four control-flow cases, actual mocked frontend switch/rollback order
and narrow automatic-field guard integration pass. Fresh native 51-route boot
uses copied SQLite, owned Mongo, the real storage owner, new staged frontend and
blocked external networking before activation.

## Activation and smoke

The frontend switched at **2026-11-02 19:32:44 UTC**. Backend f56 PID 2437301 /
invocation `ad7528f6249a4e52932624be2cf6ac84` and bot PID 2047531 /
invocation `25c8bea0ebc54016a1b6bcc78f38f104` stayed unchanged. There were zero
service restarts, no rollback and no production database restore. Protected
proofs passed, staff-before/during and forbidden departures were empty, and
unrelated configuration matched. Evidence is in
`.local/exports-plain-release/live.json` and its retained gate/activation logs.

The public entry `index-BKlInFVx.js` matched SHA256
`029882a2fb068e0c315bdc5a1eed9bec4fee57d134d0e30e137db7396f0bfdf2`.
Affected ExportWorkspace JS matched
`f4fa2341b23bbbde9041acfccaa678ecdce8ffcdf11fcf53dd3bb18cbf68b80e`
and CSS matched
`f989f5a1593e11be60ba79bef3b393eb78b3754a24ad7d9412e519b906b35fb2`.
Other preserved affected feature hashes matched their staged manifest.

Claude 428 independently confirmed runtime, public entry and zero tracebacks.
The read-only live page showed the new names, 170 rows, 179k, CWL month November
2026 and version 6. No download was pressed. Claude did not verify 360/1440 in
that round because its browser pane was hidden; the empty season selector was
the previously identified hidden-first-load bug addressed separately in PR172.
The isolated narrow/wide and eight byte-identical CSV checks remain local
validation, not proof of a production download. No production write or CSV
request was made by this release smoke.
