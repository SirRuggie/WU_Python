# Signup reminder acknowledgement and overview (129 / 134)

Source only; release remains held for owner preview. No production API, metadata read, send, role change or scheduler mutation was performed.

## Acknowledgement

The former fingerprint acknowledged a successful callback but derived generations only from explicit cycle records. Defaults-only settings therefore installed real jobs while leaving an empty generation map; unchanged polls never repaired it. This is a local reproducer, not proof of the cause of the reported 11 AM production warning.

The native scheduler now records the exact generation only after completing that cycle's job installation/removal. Its process-owned proof covers current/next and explicit cycles. Per-cycle installation is serialized. A new bot instance clears proof and receives a new process identity; a repeated Started event for the same bot retains proof. Failed or incomplete installation cannot acknowledge. The bridge retains its existing lightweight fingerprint query and existing poll, invokes the native loader when necessary, and writes an acknowledgement only when the fingerprint, process identity or installed generations change. An unchanged fingerprint can repair missing acknowledgement from already-completed native proof without replacing jobs.

The existing worker heartbeat carries process identity/readiness; the API requires current-process identity plus the exact generation. Online heartbeat is separate from loaded proof: an offline bot can have an old correctly loaded schedule and still shows the offline warning. Old process acknowledgement cannot claim that a restarted process restored jobs. No production metadata is needed for these local proofs.

Inactive settings show Off without a pending-load warning or acknowledgement polling; no backend proof is fabricated for an activation that was never requested. A future approved deployment needs a bot restart to load the native changes. Existing sent-occurrence guards, future scheduling rules, job identities, recipients and message text are unchanged. The actual native restart fixture confirms an already-sent signup occurrence stays unscheduled and no sender callback runs. This is not proof of live delivery.

## Overview

One row per editable reminder pairs Main and Lazy. Shared destinations/Notify appear once per pool when every reminder agrees; differences stay on their exact rows. Matching status/time is shown once per row; differing enabled states remain visible. Each Edit keeps the exact message/pool. The status is On, Paused or Off, with a separate warning only for offline or genuinely unacknowledged settings. Dates use the viewer's timezone without seconds; timezone is named once.

The campaign cycle is the SEND month. November 2026 send dates target December 2026 CWL, including December-to-January rollover; the label does not retime any rule. Pause confirms its scope with Pause reminders. Save confirms with Save. There is one Advanced schedule disclosure; raw role IDs remain under the existing notification editor, not a second Advanced section.

Clarified by Shaka420: six rows, one per editable reminder type (signup plus five reminders); no seventh roster row or editor. The exact short line “Roster posts are on Announcements ›” links through the existing dashboard route helper to Announcements for this season. The API still rejects roster editing here; no permission or route change. Configurable extra sequence rows use the same rendering.

## Evidence and current limits

- Same real native fixture before/after: 25 installed jobs both; old acknowledgement remains empty after another unchanged poll; fixed acknowledgement records November/December `1:0`; zero sender calls in either case (`.local/p134-baseline-reproducer.json`).
- Eight actual native tests cover defaults-only, idle no reload/write, unchanged repair, absent/failed load refusal, racing revision, restart/sent ledger, repeated Started and concurrent same-cycle installs. Existing adapter/HTTP footprint tests use an explicit simulated installer contract; they do not substitute for native proof.
- API cases cover generation mismatch, changed process, pending restore, loaded online and offline status.
- Final full frontend: 1491 passed / 263 files; TypeScript, main and isolated preview builds pass.
- Required war-reminder validation passed: 213 backend / 1 skip, 35 frontend, TypeScript/build. No delivery was attempted.
- Two required backend mutants killed by actual native assertions: acknowledge without load and skip unchanged-fingerprint repair. Differing-destination mutant fails the real rendered-content assertion. Originals restored; initial mutant runner incorrectly looked for assertion text only in stdout, corrected to include stderr.
- Browser preview covers matching/differing, paused/off/pending/offline at 360/1440, every editable message/pool and a fictional pause only. No overflow or browser errors. Initial wrapped-label selector was corrected. Initial wide preview used the sidebar grid column accidentally; fixture shell was corrected before final visual inspection. Source UI never used that malformed shell.
- Exact frozen-source boot uses 51 configured production routes, native pool, real owner on copied SQLite and owned Mongo 27169, external network blocked, config 200 / unauthenticated auth 401, cleanup and artifact hashes retained. Final boot evidence is `.local/p134-boot-final`; earlier exact checkpoints remain in `p134-boot` / `p134-boot-ready`. Full guarded backend: 6326 passed / 99 skipped / 267 subtests in 591.52 seconds. The final UI-only inactive-state correction does not change backend source; Python source hashes are compared to that full-suite revision.

## Adversarial review

Authorization, revision comparison and server-owned links remain in the same HTTP service. No recipients, destinations or new message transport rules are introduced. Invalid/stale edits still receive server errors. Generation races acknowledge only what was actually installed, and the next fingerprint catches a later edit. A failed refresh retains old rows for inspection; 401/403 clears protected state. Text renders as React text, not raw HTML. Disabled and differing settings are retained. Existing confirmation focus handling and duplicate-action guard remain in use. Native send callbacks are forbidden in the acknowledgement fixtures. No test is claimed as live Discord rendering or delivery proof.

Local preview: `http://127.0.0.1:33917/signup-reminders-preview.html`; add `?different`, `?pending`, `?offline`, `?paused` or `?off`. Fictional frontend state only; external requests are rejected. Keep this preview and its files until review ends.


## Review delta 142

Both defects reproduced before the fixes: six unchanged failed polls invoked the
native reload six times, and inactive overview rows still said On. Inactive rows
now say Off / Not scheduled and show no next-send date. The six-row fixture
matches the actual signup plus five reminder types.

An unsuccessful or incomplete native load is attempted at most once per 300
seconds for the same fingerprint and process. A configuration fingerprint change
or a new process bypasses this cooldown immediately; a successful load clears
it. Completed native proof still repairs an acknowledgement without reloading.
The cooldown is process-local and uses the existing 10-second poll; it adds no
Mongo write or polling job. The native guild scan now filters active campaign
records and projects only ownership/cycle metadata. It does not fetch unrelated
bot configuration or full campaign bodies for that scan.

A deployment must restart the bot along with the web/backend changes. New web
with an old bot correctly remains waiting until the new bot installs and proves
its jobs. This source remains held for owner preview.

Direct native regressions cover a second-job installation failure (no partial
proof), cleared process proof with an unchanged fingerprint (real reinstall),
invalid process identities, and a process replacement during installation.
The reported proof-before-install and unchanged-fingerprint mutants, plus runtime
guard and unbounded-repair mutants, all fail genuine assertions.
