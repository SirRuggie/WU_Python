# docs/

Durable project knowledge. One file per subject.

> **[editing-this-repo.md](editing-this-repo.md) — read before any bulk edit.**
> No `sed -i` / `awk` / `perl -pi` in this repo. Three incidents: twice an empty
> block that would not import, once 97 lines of double-encoded UTF-8. The two
> verification greps are there.

Written because it is fundamental, non-obvious, by-design, or was discovered
the hard way. Read this index and [editing-this-repo.md](editing-this-repo.md)
before changing durable documentation.

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
  `Context` in the pinned lightbulb (3.2.6), what does not, and the
  usage-count rule that came out of getting this wrong.

## Legal

- [terms-of-service.md](terms-of-service.md) — WU Wizard's Terms of Service,
  published for Discord app verification.
- [privacy-policy.md](privacy-policy.md) — WU Wizard's Privacy Policy,
  published for Discord app verification.

## Working with Claude

- [agent-orchestration.md](agent-orchestration.md) — the main session
  orchestrates and delegates to the agents in `.claude/agents/` (scout on
  Haiku, researcher and builder on Sonnet, refuter and debugger on Opus).
  Pricing, task-to-model reasoning, and the Claude Code mechanics behind the
  always-loaded rule in `.claude/rules/orchestration.md`.

## Features

- [accounts.md](accounts.md) — `/accounts`, the private linked-player inventory:
  row fields, ordering, pagination, stale-link policy, and failure accounting.

- [clash-of-cards.md](clash-of-cards.md) — `/cards`, the 60-card catalog,
  exception-only update flow, durable inventory shape, freshness rules,
  family matching, managed trade reservations, and the guarded scanner preview.

- [todo-dashboard.md](todo-dashboard.md) — `/todo`, as built. Data sources, the
  four views, layout rules and why, the freshness stamp, emoji slots, verified
  vs inferred. **Contains the `str()`-on-a-coc.py-enum trap — read it before
  touching any Clash state comparison anywhere in this repo.**

- [fwa-points-monitor.md](fwa-points-monitor.md) — the points.fwafarm.com
  scraper that watches every FWA clan, the watch-list rule, stored record
  fields, `/fwapoints` commands, and the Hetzner-vs-residential-IP history.

- [fwa-blacklist.md](fwa-blacklist.md) — the staff-maintained FWA opponent
  blacklist: stored fields, how entries get in (`/fwa war-plans` Blacklisted,
  `/fwa blacklist add`), and how it shows up on `/todo` and in the points
  monitor's records.

- [lazycwl-autopings.md](lazycwl-autopings.md) — the auto-ping scheduler (no
  jobstore, Mongo-backed restore), the select-all + partial-failure pattern to
  copy, and four unguarded 25-option menus that are clear only at current scale.

- [ticket-console-operations.md](ticket-console-operations.md) — the implemented
  (not yet deployed) ticket operator source of truth: safe `/ticket` + `/tickets`
  coexistence, channel setup, pilot, promotion, rollback, drain, daily
  recruiting, terminal legacy cloning, and legacy retirement.

- [ticket-console/README.md](ticket-console/README.md) — plain-English reference
  for all 22 registered v2 commands, permissions, examples, applicant actions,
  unbuilt candidate follow-up, and what changes when legacy is retired.

- [ticket-console.md](ticket-console.md) — the implemented v2 console design.
  Architecture, search, the binary flag system, ticket-history auto-detect,
  the permanence model, the chart's palette and layout, and two corrections
  against a mockup that briefly assumed things this stack cannot do.
  **Reference artifacts live in
  `docs/ticket-console/`** (`render_overview.py`, the clickable mockup) with
  the five chart icons in `assets/tickets/`.

- [legacy-ticket-migration.md](legacy-ticket-migration.md) — the implemented,
  terminal-only legacy clone: read-only Discord sources, resumable destination
  writes, staff-thread parity, immediate archive, and a one-to-five-ticket
  pilot gate. Use the operations guide above for executable commands.

## Proposals

- [todo-dashboard-proposal.md](todo-dashboard-proposal.md) — the pre-build
  research and the layout options for `/todo` (2026-08-02). Superseded as a
  description of the feature by [todo-dashboard.md](todo-dashboard.md); kept
  for the reasoning behind the options that were not taken.

- [thread-ticketing-proposal.md](thread-ticketing-proposal.md) — research and
  historical design for thread-based ticketing + the console dashboard
  (2026-08-02). Kept for research and component-budget reasoning; its rollout,
  command, and migration plans are superseded by the
  [operations guide](ticket-console-operations.md).

- [media-hosting.md](media-hosting.md) — why `/todo` burned through
  Cloudinary's free bandwidth (hikari 2.3.5 downloaded every image URL on
  every render; full-size originals used as thumbnails), the free-hosting
  comparison — Discord-native, Cloudflare R2, object stores, Cloudinary-likes —
  and the migration (2026-09-02). **Decided: Cloudflare R2, implemented;
  the hikari double-fetch fix is closed by the 2026-09-08 upgrade to
  hikari 2.6.0.**

## Architecture

- [components-v2-in-hikari.md](components-v2-in-hikari.md) — what hikari can
  actually build vs. what Discord supports. **Modals are text-input only.**
- [component-dispatcher.md](component-dispatcher.md) — how every button, select
  and modal is routed, plus the dispatcher's known defects.
- [ticket-data-model.md](ticket-data-model.md) — historical pre-pilot store
  notes. For the implemented split (`button_store` legacy, `tickets` v2), use the
  ticket console operations guide.
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
