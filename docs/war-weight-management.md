# War Weight management

Open **/manage → FWA → War Weight**. Administrator permission is checked both when opening the panel and on every change.

- **Edit a Town Hall:** change its minimum/maximum total war weight and emoji.
- **Add Town Hall:** add a new level, including future levels such as TH19. Enter actual known ranges; the bot does not invent future game values.
- **Lowest Town Hall to show:** choose TH13 to display TH13 through the highest configured level. This only filters the reference guide, not the calculation or FWA suitability threshold.
- **Emoji:** blank automatically matches `TH_<level>` or `TH<level>`, case-insensitively, in cached guild emojis or application emojis. A custom emoji name or pasted Discord custom emoji overrides this. Existing built-in Town Hall emojis remain fallbacks, followed by 🏛️.

`/fwa weight` remains the calculator. It reads these settings for each new result; existing messages are not rewritten. Existing TH9–18 ranges and minimum TH9 remain the defaults until edited. Total weights must be 1–500,000, increasing, nonoverlapping, with minimum less than maximum. Up to 25 configured entries are supported. The existing 115,000 FWA suitability threshold is unchanged.

## Storage and ownership

Owner: `utils/war_weight.py`. Permanent `war_weight_settings` collection in the database backing `mongo.fwa_data`; one document per guild, string guild ID as `_id`, schema version 1. Fields: `guild_id`, `ranges` keyed by Town Hall number, `minimum_th`, `revision`, `updated_by`, `updated_at`. No TTL and no `button_store` usage. Defaults are read without writing; the first edit creates the record. Revision-based compare-and-swap prevents stale panels/modals from replacing newer settings.

Private editor sessions use the existing TTL-backed `component_state` collection for 30 minutes and bind the guild, user, editor type, and revision. Durable settings survive restarts independently of these sessions.

## Manual CWL player weights

Dashboard manual weights carry into later signups by normalized player tag. Existing season values and published snapshots are not rewritten. “Restore source” stops carrying the manual override into future signups; previous values remain in history. Staff account details show the first saved manual weight.

`cwl_web/player_weights.py` owns permanent `player_manual_weight_history` in the database backing `mongo.fwa_data`, scoped to the server. Each immutable event records player tag, weight (null when cleared), season, staff ID, and UTC time. No TTL or seasonal deletion. Existing roster edit audit records are migrated once, with current manual entries as fallback. Original weights can only be recovered where historical records still exist.

The roster write and local SQLite outbox commit together. The web service syncs every 30 seconds with majority Mongo acknowledgement, retrying queued events after failures/restarts without duplicates. Mongo events rebuild the local cache after recovery. SQLite and the full Mongo databases are covered by the existing backup jobs. No bot restart or Discord command changes are required.

## Official clan weights (2026-10-21)

**Clan management → Clan weights** is now the official saved source for CWL.
Existing player-tag values, history, storage counts, and attribution are promoted
in place. The legacy `weight-trial` view/API and `clan_weight_trial` table names
remain for compatibility; there is no copied or second weight ledger.

Precedence: saved clan weight, then explicit staff override, then FWA Stats only
for a tag with no saved row. A saved blank deliberately means Not Available and
suppresses external fallback. The official source follows the player if they
leave their clan. Current FWA members can be edited from their clan; Find any player can update an existing saved row after the player leaves. It cannot create a saved row for a random non-member.

Current roster reads, placement calculations, member account weights, refreshes,
and replacement suggestions use the saved source. A changed saved weight bumps
all affected draft roster revisions in the same transaction, invalidating stale
placement previews. Existing assignments and immutable published snapshots are
not rewritten or automatically republished. Staff can retain deliberate manual
overrides; those must be cleared through the existing override controls to use
the official source for that account.

## Persistent war ordering

`clan_weight_war_lineups` stores one latest valid lineup per clan in the same
durable database. Opening the editor captures valid current/preparation/ended
wars; a server worker also checks FWA clans at startup and every ten minutes.
Older responses, state regressions, malformed rosters, and unavailable/private
wars cannot erase a saved lineup. API team size must match returned members.

If the API stops returning a lineup, show the saved order with its capture time
and a reminder to match the destination spreadsheet. Membership is always live;
departed players are not reinserted into the editable member list. Existing
Column F safety checks still reject copying if war members/weights are missing.
This is the latest **observed** war, not guaranteed reconstruction of wars that
finished while the service was offline and were never captured. A newly captured
war replaces the previous lineup, preventing unbounded lineup history growth.

## Recovery and validation

Saved weights, audit history, and lineups participate in the shared Mongo-backed
dashboard checkpoint before a successful save response. See [dashboard recovery](cwl-dashboard.md#dashboard-database-recovery-2026-10-21).

Regression scope: source precedence, clearing, fallback outages, cached member
views, preview revisions and replay, current-member filtering, capture without
an editor visit, restart persistence, older/invalid responses, and Mongo recovery.
UI checked with isolated 50-member fixtures at desktop, 390px, and 320px: official
labels, compact FWA selector, readable fields, and no horizontal page overflow.
No production weights were altered for verification; no live messages were sent.

## Linked-weight follow-up

Weight edits require Clan weights access (or owner access). Roster-only staff
can still place players and refresh the queue; clicking its edit control shows
an in-app permission notice instead of opening the editor. Historical values
such as 151500 remain unchanged on open. Explicit Clear followed by Save can
set them to Not Available; Clear alone does not write.

The bot retains legacy weights when the linked table is absent and treats an
invalid timestamp as unavailable instead of crashing. Working roster exports
label the old field `legacy_manual_weight` alongside `effective_weight`;
published exports keep their snapshot columns. Archived-season freezing is
not part of this change, per the owner's decision.

## Linked-weight follow-up release — October 30

`linked-weight-followup-1` / PR81 is live at
`370797052fc0238632916af785174ff730292ef4` on frontend, backend and bot.
It makes Clear reachable for historical non-thousand values, preserves legacy
weights when the linked table is absent, labels the working export's legacy
column, and shows the roster-only permission notice without opening an editor.
Public `index-BLr7_MkH.js` SHA-256:
`34eb9f2a51355b38a10a96f58ac495729b83f1703e8b392c060c8183b9a09a51`.

Integrated validation: 5,004 backend tests (21 skipped, 162 subtests), 1,045
frontend tests, TypeScript/build. The clean tagged release differs from the
integration-tested code only in Avatar release docs. Startup imports, active cwd,
two consecutive public config 200s, public assets and anonymous denial checks
passed. Bot restarted after the lease-expiry wait; first scanner pass reported
25 clans, zero wars finalized and eight behind. Current journals were clean.

Backup `.local/linked-weight-followup-1-backup-20261030T213342Z` is retained.
Protected SQLite tables matched, including 155 signups, four publications and
seven saved lineups. Active strikes stayed 3,558; no unexplained changes. All
12 Mongo collection checks and raw moderation settings matched. No scripted live
message or authenticated write was performed. Code-only rollback retains
frontend/backend `44a3708` and bot `fb46bd3`; never restore the DB for code rollback.
The guarded local coordinator is `/tmp/wu-linked-followup-release/run.py`.

Claude's read-only production smoke passed: runtime revisions and public entry
matched; at 360px Gnar's Details showed Loot 34800 / Full 174000, Save disabled
when clean and Clear enabled, with no errors or overflow. Closed without a write.
The roster-only notice remains covered by accepted tests, not the owner session.
