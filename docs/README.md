# docs/

Durable project knowledge. One file per subject.

> **[editing-this-repo.md](editing-this-repo.md) — read before any bulk edit.**
> No `sed -i` / `awk` / `perl -pi` in this repo. Three incidents: twice an empty
> block that would not import, once 97 lines of double-encoded UTF-8. The two
> verification greps are there.

Written because it is fundamental, non-obvious, by-design, or was discovered
the hard way. The standing instruction that governs this folder is in
[`../CLAUDE.md`](../CLAUDE.md).

## Stack & environment

- [deployment.md](deployment.md) — the Hetzner box, venv path, systemd, remote
  Mongo, `.env`. None of it discoverable from the repo.
- [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md) — which versions
  actually run, the unpinned-requirements problem, and the unresolved
  2.3.5 / 2.4.1 discrepancy.
- [hikari-logging-and-warnings.md](hikari-logging-and-warnings.md) —
  `GatewayBot.__init__` silently takes over `logging` and `warnings.filters`.
  Any warning filter installed before it is dead. Cost three attempts.
- [lightbulb-context-api.md](lightbulb-context-api.md) — what exists on
  `Context` in 3.0.3, what does not, and the usage-count rule that came out of
  getting this wrong.

## Features

- [accounts.md](accounts.md) — `/accounts`, the private linked-player inventory:
  row fields, ordering, pagination, stale-link policy, and failure accounting.

- [todo-dashboard.md](todo-dashboard.md) — `/todo`, as built. Data sources, the
  four views, layout rules and why, the freshness stamp, emoji slots, verified
  vs inferred. **Contains the `str()`-on-a-coc.py-enum trap — read it before
  touching any Clash state comparison anywhere in this repo.**

- [lazycwl-autopings.md](lazycwl-autopings.md) — the auto-ping scheduler (no
  jobstore, Mongo-backed restore), the select-all + partial-failure pattern to
  copy, and four unguarded 25-option menus that are clear only at current scale.

## Proposals

- [todo-dashboard-proposal.md](todo-dashboard-proposal.md) — the pre-build
  research and the layout options for `/todo` (2026-08-02). Superseded as a
  description of the feature by [todo-dashboard.md](todo-dashboard.md); kept
  for the reasoning behind the options that were not taken.

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

- [discord-rate-limit-buckets.md](discord-rate-limit-buckets.md) — which REST
  routes share a bucket and which do not. FWA sync DMs and `/todo` competed for
  one; a deferral competes with nothing.
- [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md)
  — 9 user-facing failures in 78 minutes. Capacity ruled out, root cause never
  established, mitigated. Recorded so nobody re-investigates from scratch.

## Integrations

- [clashking-war-endpoints.md](clashking-war-endpoints.md) — historical CWL, the
  real payload shape, and how ClashKingBot's own to-do command works.
- [clashking-discord-links.md](clashking-discord-links.md) — the Discord↔Clash
  link API. Bidirectional, unauthenticated, how to read its response, and the
  `/accounts` completeness policy.

- [coc-maintenance-detection.md](coc-maintenance-detection.md) — how coc.py
  signals Clash maintenance. **There is no flag and no end time — only a 503
  raised as `coc.Maintenance`.** Where it is raised, why our four existing
  handlers cannot tell it apart from any other HTTP error, and the sites that
  do not handle it at all.

- [band-ical-feeds.md](band-ical-feeds.md) — the per-calendar iCal feeds, why
  they are treated as credentials, and why the BAND Open API was not usable.
