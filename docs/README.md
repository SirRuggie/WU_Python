# docs/

Durable project knowledge. One file per subject.

Written because it is fundamental, non-obvious, by-design, or was discovered
the hard way. The standing instruction that governs this folder is in
[`../CLAUDE.md`](../CLAUDE.md).

## Stack & environment

- [deployment.md](deployment.md) — the Hetzner box, venv path, systemd, remote
  Mongo, `.env`. None of it discoverable from the repo.
- [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md) — which versions
  actually run, the unpinned-requirements problem, and the unresolved
  2.3.5 / 2.4.1 discrepancy.
- [lightbulb-context-api.md](lightbulb-context-api.md) — what exists on
  `Context` in 3.0.3, what does not, and the usage-count rule that came out of
  getting this wrong.

## Proposals

- [thread-ticketing-proposal.md](thread-ticketing-proposal.md) — research and
  design for thread-based ticketing + the console dashboard (2026-08-02).
  Findings, dashboard design, migration plan, risks. **Not yet decided.**

## Architecture

- [components-v2-in-hikari.md](components-v2-in-hikari.md) — what hikari can
  actually build vs. what Discord supports. **Modals are text-input only.**
- [component-dispatcher.md](component-dispatcher.md) — how every button, select
  and modal is routed, plus the dispatcher's known defects.
- [ticket-data-model.md](ticket-data-model.md) — where ticket documents live and
  why that is not where you would expect.
- [ticket-status-lifecycle.md](ticket-status-lifecycle.md) — the real status
  values, and why `closed` has one document and open tickets accumulated.
- [ticket-channel-naming.md](ticket-channel-naming.md) — the ✅ → 🆕 prefix
  change, and why an old ✅ channel is open rather than closed.

## Incidents

- [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md)
  — 9 user-facing failures in 78 minutes. Capacity ruled out, root cause never
  established, mitigated. Recorded so nobody re-investigates from scratch.

## Integrations

- [band-ical-feeds.md](band-ical-feeds.md) — the per-calendar iCal feeds, why
  they are treated as credentials, and why the BAND Open API was not usable.
