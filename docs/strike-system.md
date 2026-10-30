# Account strikes

Implemented for the Warriors United Discord bot and its existing dashboard. This document describes the new system; `botghost-strike-sentinel-investigation.md` describes the old BotGhost reference.

## Rules

- Track registered family clans together, including FWA.
- Only complete, ended, regular wars with an explicit two-attack limit qualify
  for automatic strikes. CWL is informational history without strikes.
- Both attacks missed: one strike. One missed: history only. Both used: no strike.
- Strikes belong to the player tag. Member lookup includes linked accounts. Moving clans does not clear history.
- Active strikes expire 60 days after the war ended, or after a manual strike was added. Expired and removed records remain available.
- No automatic punishment.

## Streaks and departure grace — prompt 25 implementation

For newly finalized official-API captures, a played war means the account was
in an ended regular-war lineup and used both attacks. Every second consecutive
played war (2 and 4) clears the oldest active strike. At six played wars, all
active strikes clear and the streak resets to zero. Missing one or both attacks
breaks the streak; missing both still gives one strike. Not being in the lineup,
approved leave, exempt roles, CWL and incomplete final captures neither build nor
break the streak. Historical imports and previously finalized wars do not
retroactively build streaks.

Clearing retains the ledger record as removed, with system attribution and
`Cleared by streak (2 wars played)` or `Reset by streak (6 wars played)` as the
reason. The existing 60-day expiry remains: expiry or streak clearing can end an
active strike. Storage and finalization must preserve idempotence across retries
and restarts; the integrated backend review records that evidence separately.

The account detail shows its current streak and next milestone independently of
paginated or filtered history. Loading and unavailable streak data remain
distinct from a confirmed zero. Late responses for a previous account cannot
replace the current account's streak.

The top-of-page **How strikes work** button opens the shared ActionPanel, including
phone sheet layout, Close, Escape, Back and focus behavior. Canonical help wording
lives in `web/cwl/src/strikeHelp.ts`; `StrikeHelpText` and its plain-text helper
share it for future member-card/DM consumers. Body text is 16px and the Close
target is at least 44px. The current shared help default is **4 strikes**; prompt
23 will add the configurable setting and wire its value into the help. This
batch does not add a settings editor or automated replacement.

A confirmed departed account remains in Replacements during its 48-hour grace
period with an explicit **Left clan** label and its last-seen clan/time. A stale
roster alone is not labeled as a confirmed departure. After more than 48 hours
out of that clan, it no longer appears and its priority is cleared with
`Left clan (48h)`; strike history remains. A return during grace keeps the mark.
After cleanup, a returning account appears only if it qualifies again.

Frontend validation covers exact help copy and limit substitution, panel
Close/Escape/Back, streak milestones and unavailable data, late account responses,
and confirmed-departure versus stale-roster rendering. Changes add no client-side
writes. Narrow/wide browser screenshots, integrated backend failure-mode tests,
mutation checks and release verification remain integration gates; these unit
checks are not live delivery or a full assistive-technology audit.

## Staff workflow

The **Strikes** dashboard has History, Leave, Exempt roles, and Import wars tabs. **Replacements** is a child page beneath Strikes in the sidebar.

History starts with one row per player account with active strikes, ordered by active strike count. All accounts also shows inactive and missed-only accounts. Accounts linked to the same Discord member remain separate. Open an account to see strike dates, war matchups, and removal history. One-missed records stay hidden unless selected. Find a war by clan or opponent, then choose its date to see that war’s missed attacks. History supports player, Discord member, clan, and status searches; add a manual strike with a reason, or remove a strike with a reason. Choosing a member lets staff choose the player account.

The Replacements page shows marked accounts and accounts with active strikes, grouped by family clan. Use Add accounts to choose a family clan and check accounts from its current roster, or enter a player tag. Selected accounts share Chopping Block, High priority, or Normal and an optional note. Accounts already manually listed are left unchanged. The clan roster is checked again on save. Marking or clearing a replacement never adds or removes strikes. Clearing a priority removes its note and manual listing; an account with active strikes still appears as a normal candidate. Preferences apply to the clan where they were set, so moving clans does not transfer that preference. Existing filler marks appear as Chopping Block.

Enter an optional recruit weight on the same page to find FWA matches. Known weights rank by replacement priority, active strikes, then nearest weight; unknown weights are clearly marked and appear after known matches. Without a recruit weight, accounts remain visible even when their weight is unknown. Existing roster weights and manual weight overrides are reused.

Leave starts when approved and resumes tracking at **00:00 UTC on the selected date**. All currently linked accounts are selected initially; staff can uncheck individual accounts.

Role `769130325460254740` is excluded by default. Staff can change the list in Exempt roles. Current role membership is used for imports; historical role membership cannot be reconstructed. Missed attacks for exempt accounts are recorded without adding a strike. Unknown roles or conflicting/unavailable links defer processing.

Discord commands use Components V2 responses: `/strikes view`, `/strikes add`, `/strikes remove`, and `/strikes replacements`. The replacements command opens family accounts with active strikes or a manual replacement mark in a paginated channel-visible message. Its controls belong to the staff member who opened it; other strike commands remain ephemeral. Unmarked accounts with zero active strikes are excluded, including when filtering by weight. Clan, Town Hall, weight and sort controls refine that list; reset returns to all eligible replacement accounts. Weight 149 means 149k (149000 also works). Rows show clan names, TH, compact weights and active strikes. The panel opens from saved rosters maintained by the background monitor; opening or filtering never waits for external roster or weight requests. Weight feeds refresh in the background, with saved values used meanwhile. Unknown TH or weight stays labeled unknown, and old clan snapshots show Last known. Leave, exempt roles, filler preferences, and import review are managed in the dashboard.

## Import and monitoring

Check past wars to preview up to 60 days of available saved history. Preview and apply run as background jobs; the dashboard polls short status requests so large imports do not hit the web proxy timeout. Reloading the page resumes the same job. Jobs stop if the web service restarts; retrying is safe because ledger records are deduplicated. Review incidents, uncheck unwanted records, then import. Availability depends on the external archive. The interface reports coverage and unavailable clans; incomplete or ambiguous wars are skipped rather than guessed.

The bot starts a ten-minute monitor through its normal extension lifecycle. The
current-war monitor observes official Clash API wars; it does not silently
import old wars on startup. Historical imports require the preview/apply
workflow. Deterministic war/player IDs prevent a repeated scan or import from
adding duplicate strikes. Manual submissions use request IDs to protect retries.

Both interfaces use the same MongoDB ledger. Access has three independent options:

- **Strikes · Settings**: history, replacements, leave, role exemptions and filler preferences.
- **Strikes · Add**: manual strikes and reviewed imports; also authorizes `/strikes add`.
- **Strikes · Remove**: removing strikes; also authorizes `/strikes remove`.

Any of these options includes viewing history and replacements. Add does not grant removal; Settings does not grant either manual action. Select all three for full dashboard access. Discord Administrators retain access to all strike commands. Other users need the matching dashboard grant. Discord commands and account-selection buttons reread shared grants, so revoked access cannot authorize a later action. Dashboard writes also retain authentication and CSRF protections.

## Main files

- `utils/strike_store.py`: ledger, exemption rules, expiry, ranking, import preview/apply.
- `utils/strike_wars.py`: historical ClashKing import retrieval, pagination, coverage, validation.
- `utils/strike_official.py`: normalization of official current-war and CWL observations.
- `utils/strike_tracking.py`: durable official-war snapshots and per-clan tracking health.
- `extensions/commands/strikes.py`: Discord Components V2 commands and monitor lifecycle.
- `cwl_web/strikes.py`: dashboard API.
- `web/cwl/src/StrikesWorkspace.tsx`: dashboard interface.

## Operational limits

Deploy through the normal bot and dashboard services. Restart the existing bot service; do not start a second gateway process. Historical imports remain an explicit staff preview/apply action after deployment.

Archived wars are best effort, not a guaranteed 60-day history. A current roster refresh is required before replacement candidates appear. Discord display and live provider behavior still need a production smoke check after release; local UI checks use fixture data.

Import eligibility is account-based. Both ClashKing and ClashPerk are checked; an account with no owner in either successful result can receive a strike and displays Not linked. Conflicting owners or failed role checks defer only that account into Needs review, without writing a ledger record. A confirmed Discord member-not-found response means no current server roles; other Discord errors remain unknown. Provider-wide link outages still defer affected wars, preserving role exclusions. Deferred accounts must be checked again in a fresh preview before import; applying an older preview never adds newly resolved accounts without review.

CWL wars are recorded separately as informational history. They show each account's single attack used or missed, and are labeled CWL · No strikes. They never add active strikes, strike totals, expiry penalties, or replacement priority. Regular wars still require an explicit two-attack limit. CWL history is visible through Find war and All records, while the default active-strike view stays unchanged. CWL records use separate IDs and are safe to load repeatedly.

## Tracking health

The Accounts page has a compact Tracking status section. Each family clan shows
its last completed check, last successful check, last recorded war, current
official war state, and any current problem. A failed or partial check preserves
the previous successful timestamp. The visible health states are On track,
Behind, War log private, and Error. An absent war record and unconfirmed
current-war state must not produce a green On track summary. A confirmed
`notInWar` response can be on track without a new record; an unfinished final
check, stale active-war record, or missing observation is not silently healthy.
Saved error details use plain, safe messages instead of raw provider responses.

Retry queues a durable clan check for the bot and requires Add strikes access, because checking a war can create strikes. Automatic checks continue normally. Tracking status is shared through MongoDB, so dashboard and bot restarts do not erase the previous result.

Import past wars is a collapsed section under Settings for occasional backfills. It requires Add strikes access; exempt-role settings still require Manage strikes access. Existing import jobs and previews can be resumed there.

## October 23 dashboard workflow review

- Accounts is the default view. Manual strikes use a focused account/reason form,
  then explicit review and confirmation. Member lookup requires an account choice;
  late lookups cannot replace a newer selection. Failed saves retain the draft and
  request ID. Account history returns to the previous search.
- Approved leave remains visible; approval is disclosed on demand and ending leave
  has inline confirmation. Settings retains role exclusions and collapsed imports.
  No strike eligibility rules or data migrations changed.
- Replacements uses compact clan-grouped rows, Edit/Cancel controls and an optional
  Match recruit weight disclosure. Adding accounts is a focused flow; failed writes
  refresh eligibility while retaining valid selections and notes. Drafts participate
  in dashboard navigation and browser-exit protection.
- Replacement weights use the shared official Clan weights overlay: saved clan
  weights (including explicitly unknown values), then manual fallback, then the
  external feed. This corrects the former manual-first behavior.

Validation: production frontend build; 275 frontend tests; 178 strike/replacement
backend tests, including official/manual/unknown weight precedence. Isolated browser
checks at 320px, 390px and 1280px covered escaped player/reason text, delayed member
lookup, manual review before saving, failed saves with the same request ID, retained
replacement drafts, FWA weight matching, edit cancellation and mobile end-leave
confirmation. No live strikes, roster entries or Discord messages were created.

Limits: the browser tool stalled on the native discard confirmation, so its accept/
cancel behavior was not fully exercised. Full screen-reader and physical-device
testing remain outstanding. Existing simultaneous replacement edits and role-list
settings are last-write-wins; this UI pass adds no version-conflict protocol.
Notification/provider delivery was not verified by isolated fixture checks.

## Official war monitor — released October 30, 2026

`strike-tracking-2` (`6a2f8d735d1ee6e5ea912be10d3bba75a143ce09`, PR #61)
is live in the frontend, isolated backend, and bot. Claude's read-only smoke
passed. The first completed official pass checked 25 clans, finalized zero wars,
and found 13 Behind; the tracking card showed 12 On track / 13 Behind, with no
private or error states. The 13 Behind clans reflect current/incomplete wars and
older last-recorded wars; no historical-gap backfill ran. No live test strikes or
Discord messages were sent. See [backend release evidence](dashboard-backend-releases.md#strike-tracking-2--october-30-2026).

For automatic strike
tracking, the official Clash API is the source for data it exposes: the current
regular war and CWL league group/war tags. ClashKing remains a source for Discord
account links, the separate player battle-log history feature, and the explicit
**Import past wars** tool for historical wars. Routine `scan_once` does not read
ClashKing war history. Imported records are labeled `ClashKing (import)`; records
captured by this monitor are labeled `Clash API`. Older automatic ClashKing
records retain the honest `ClashKing (legacy)` label. The existing ledger's
`source` values (`war`, `cwl`, and manual) keep their original meaning.

Each full poll checks every tracked clan's current war with the bot's existing
official API client. Preparation and in-war observations are stored in Mongo as
snapshots keyed by clan tag, opponent tag, and end time, matching the ledger war
identity. A snapshot contains war type and attack limit, timing, both clans,
and member positions, Town Halls, and observed attacks. CWL league-war
observations use the official league group and war tags; CWL remains
informational and cannot add strikes. Friendly and other ineligible wars are
observations only. The shared preparation-time classifier treats listed friendly
lengths, including 24 hours, as friendly within two minutes; only a 23-hour
preparation within 45 minutes is a regular war. Missing or other timing is
unknown and cannot create strikes. The explicit ClashKing import uses the same
rule even when stored wars omit a type field; rejected wars appear in skipped
coverage. Complete ended CWL responses are cached across checks to avoid
refetching stable war tags; active and incomplete responses are fetched again.

An observed active war receives a follow-up check about a minute after its end,
with bounded backoff when the official source or final payload is unavailable.
A persisted snapshot and due time survive bot restarts. Only an official
`warEnded` response with a complete roster and attack counts can reach the
existing `process_war` strike rules, and only a regular two-attack war can add
automatic strikes. Two missed attacks still yield one strike; one missed attack
is history only. Existing leave, exemption, account-link review, expiry, and
idempotent war/player keys continue to govern the ledger. A final response
first seen without an earlier active observation is not backfilled as a strike.
If a later war replaces an observed war before a usable final snapshot arrives,
that war is marked incomplete, appears in **Find war** with a review message and
zero automatic strikes, and makes tracking Behind. No historical-gap backfill
or missed-war report is part of this batch.
An older incomplete war remains visible in Find war but no longer keeps a clan
Behind after a newer completed war. Open snapshots for removed family clans are
abandoned once, without strikes or repeated due checks.

The API and tracking card show each clan's last recorded war date, current war
state (`notInWar`, preparation, in war, ended, private, or unknown), and health.
On track requires a confirmed not-in-war state or a completed latest-war path;
Behind includes a missed final check or a last recorded war over three days old
for a clan that has warred. An unknown state is never On track. Private war logs
and source errors remain distinct from success. Invalid Clash API key/IP reasons,
or 403 responses from every tracked clan in a full check, show an error rather
than War log private. The summary counts
these states rather than treating an empty war result as green. A staff Retry
queues a durable check and still requires Add strikes access, since a completed
check may create a strike. Each monitor pass logs a compact success line with
clan, finalization, and nonhealthy counts; source failures remain visible.

Release checks included 4,830 backend tests passed (21 skipped), 906 frontend
tests, TypeScript and the clean tagged frontend build, backend startup,
one completed official-API pass, public asset hashes, protected data comparison,
and Claude's read-only smoke. A durable SQLite and Mongo backup was verified
before activation. The release expired no import previews because none were
active. The earlier network-isolated fixture results remain separate from this
production evidence.

### Later — non-blocking review items

- Add tests that kill the surviving mutations: missing prep treated as regular,
  any other prep length treated as regular, removing `abandon_untracked` from
  `scan_once`, and caching ended but incomplete CWL wars.
- Deduplicate tracked clans, or use consistent cardinality in the all-403 guard,
  so duplicate clan documents cannot make a partial check look like every clan
  returned 403.
- In the all-403 case, align the displayed war state with Error; it currently
  still reads “War log private.”
- Review whether the three-day stale health rule should apply to idle clans.
  This affects health only, never strike creation.
- Repair the installed frontend staging helper for nested assets such as
  `assets/tour`; this release used a reviewed scratch helper after the standard
  helper failed during staging. The installed helper was not changed.
Full integrated tests and deployment evidence will be recorded by the release
review; none are claimed by this development section.
