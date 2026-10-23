# Roster loading — October 23, 2026

The staff roster previously waited for live player locations, the family directory,
and every host's league before returning saved assignments. League requests held
one global lock across all external calls, creating head-of-line blocking between
pages. This was a concrete server-side blocking path, not a bundle-size diagnosis.

## Changes

- The roster UI requests the saved snapshot immediately with optional metadata
  enrichment in background jobs. Weights, assignments, locks and editing controls
  are usable while a small status line explains that live details are updating.
- Per-player and per-clan jobs are shared across requests. Fresh league cache hits
  no longer wait behind unrelated clans. Legacy metadata callers wait at most
  three seconds for enrichment, then receive explicitly stale/unknown metadata.
- Provider transport retries remain the single retry owner for background player
  checks. Failed checks have a cooldown; unknown data is not treated as outside
  the family or as an Unranked league. The family display cache is not used for
  authorization or signup validation.
- Visible roster polling is sequential and bounded to 90 seconds. Navigation and
  new explicit reads invalidate old responses. Background responses merge only
  live display fields, never assignments, weights, membership or local editor
  values. A changed revision asks staff to refresh. Authorization failures clear
  protected roster state. Existing write revision checks remain in force.
- Jobs are cancelled at application shutdown; player/league caches and player
  failure maps are bounded. There is no durable storage migration.

## Review and evidence

122 backend tests passed across roster, metadata, retry, foundation and readiness
suites. Coverage includes a blocked player/clan/directory fixture where the saved
HTTP roster returns within one second, repeat-request deduplication, eventual live
metadata, denied member access, cached reads beside blocked lookups, failure
cooldowns, stale-data semantics, and cancellation at shutdown. This is an isolated
latency assertion, not a measured production/mobile speed guarantee.

321 frontend tests passed, including metadata-only merge and rejection of a
mismatched revision. TypeScript and the production build passed. Manual code review
checked editor state retention, season/request races, authorization loss, bounded
polling, hidden-page polling, and unchanged mutation paths.

A narrow/wide isolated browser preview was prepared, but this run's browser refused
both loopback URLs with ERR_BLOCKED_BY_CLIENT. Therefore no rendered/browser or real
phone verification is claimed for this release. The only new visible UI is a
wrapping status paragraph; existing roster layout and controls are unchanged.
Existing aiohttp application-key warnings remain. No live Discord messages or
roster edits were used as tests.

Scope: this removes a roster bottleneck and shared league-cache blocking. Cold
linked-account discovery and general initial app/network performance remain
separate areas to measure; this is not a claim that every page is now instantaneous.
