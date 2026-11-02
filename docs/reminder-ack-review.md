# Signup reminder acknowledgement and overview (129 / 134)

Source review in progress; release remains held for owner preview. No production API, metadata read, send, role change or scheduler mutation was performed.

## Acknowledgement

The former fingerprint acknowledged a successful callback but derived generations only from explicit cycle records. Defaults-only settings therefore installed real jobs while leaving an empty generation map; unchanged polls never repaired it. This is a local reproducer, not proof of the cause of the reported 11 AM production warning.

The native scheduler now records the exact generation only after completing that cycle's job installation/removal. Its process-owned proof covers current/next and explicit cycles. Per-cycle installation is serialized. A new bot instance clears proof and receives a new process identity; a repeated Started event for the same bot retains proof. Failed or incomplete installation cannot acknowledge. The bridge retains its existing lightweight fingerprint query and existing poll, invokes the native loader when necessary, and writes an acknowledgement only when the fingerprint, process identity or installed generations change. An unchanged fingerprint can repair missing acknowledgement from already-completed native proof without replacing jobs.

The existing worker heartbeat carries process identity/readiness; the API requires current-process identity plus the exact generation. Online heartbeat is separate from loaded proof: an offline bot can have an old correctly loaded schedule and still shows the offline warning. Old process acknowledgement cannot claim that a restarted process restored jobs. No production metadata is needed for these local proofs.

A future approved deployment needs a bot restart to load the native changes. Existing sent-occurrence guards, future scheduling rules, job identities, recipients and message text are unchanged. The actual native restart fixture confirms an already-sent signup occurrence stays unscheduled and no sender callback runs. This is not proof of live delivery.

## Overview

One row per editable reminder pairs Main and Lazy. Shared destinations/Notify appear once per pool when every reminder agrees; differences stay on their exact rows. Matching status/time is shown once per row; differing enabled states remain visible. Each Edit keeps the exact message/pool. The status is On, Paused or Off, with a separate warning only for offline or genuinely unacknowledged settings. Dates use the viewer's timezone without seconds; timezone is named once.

The campaign cycle is the SEND month. November 2026 send dates target December 2026 CWL, including December-to-January rollover; the label does not retime any rule. Pause confirms its scope with Pause reminders. Save confirms with Save. There is one Advanced schedule disclosure; raw role IDs remain under the existing notification editor, not a second Advanced section.

Boundary: the default schema has signup, five reminders and roster. Roster editing remains in Publish roster and the API explicitly rejects editing it here. No seventh editable path was invented. Owner clarification on the requested seven-type overview is pending; configurable sequence rows are supported by the same rendering.

## Evidence and current limits

- Same real native fixture before/after: 25 installed jobs both; old acknowledgement remains empty after another unchanged poll; fixed acknowledgement records November/December `1:0`; zero sender calls in either case (`.local/p134-baseline-reproducer.json`).
- Eight actual native tests cover defaults-only, idle no reload/write, unchanged repair, absent/failed load refusal, racing revision, restart/sent ledger, repeated Started and concurrent same-cycle installs. Existing adapter/HTTP footprint tests use an explicit simulated installer contract; they do not substitute for native proof.
- API cases cover generation mismatch, changed process, pending restore, loaded online and offline status.
- Full frontend initially 1487 passed / 262 files; TypeScript, main and isolated preview builds pass. Final UI refinements require refreshed checks before READY.
- Required war-reminder validation passed: 213 backend / 1 skip, 35 frontend, TypeScript/build. No delivery was attempted.
- Two required backend mutants killed by actual native assertions: acknowledge without load and skip unchanged-fingerprint repair. Differing-destination mutant fails the real rendered-content assertion. Originals restored; initial mutant runner incorrectly looked for assertion text only in stdout, corrected to include stderr.
- Browser preview covers matching/differing, paused/off/pending/offline at 360/1440, every editable message/pool and a fictional pause only. No overflow or browser errors. Initial wrapped-label selector was corrected. Initial wide preview used the sidebar grid column accidentally; fixture shell was corrected before final visual inspection. Source UI never used that malformed shell.
- Full backend and exact staged production-shaped boot are pending their coordinated gates. No READY claim yet.

## Adversarial review

Authorization, revision comparison and server-owned links remain in the same HTTP service. No recipients, destinations or new message transport rules are introduced. Invalid/stale edits still receive server errors. Generation races acknowledge only what was actually installed, and the next fingerprint catches a later edit. A failed refresh retains old rows for inspection; 401/403 clears protected state. Text renders as React text, not raw HTML. Disabled and differing settings are retained. Existing confirmation focus handling and duplicate-action guard remain in use. Native send callbacks are forbidden in the acknowledgement fixtures. No test is claimed as live Discord rendering or delivery proof.

Local preview: `http://127.0.0.1:33917/signup-reminders-preview.html`; add `?different`, `?pending`, `?offline`, `?paused` or `?off`. Fictional frontend state only; external requests are rejected. Keep this preview and its files until review ends.
