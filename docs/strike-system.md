# Account strikes

Implemented for the Warriors United Discord bot and its existing dashboard. This document describes the new system; `botghost-strike-sentinel-investigation.md` describes the old BotGhost reference.

## Rules

- Track registered family clans together, including FWA.
- Only complete, ended, regular wars with an explicit two-attack limit qualify. CWL is deferred.
- Both attacks missed: one strike. One missed: history only. Both used: no strike.
- Strikes belong to the player tag. Member lookup includes linked accounts. Moving clans does not clear history.
- Active strikes expire 60 days after the war ended, or after a manual strike was added. Expired and removed records remain available.
- No automatic punishment.

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

The bot starts a ten-minute monitor through its normal extension lifecycle. A persisted activation time prevents initial startup from silently importing old wars. Historical imports require the preview/apply workflow. Deterministic war/player IDs prevent a repeated scan or import from adding duplicate strikes. Manual submissions use request IDs to protect retries.

Both interfaces use the same MongoDB ledger. Access has three independent options:

- **Strikes · Settings**: history, replacements, leave, role exemptions and filler preferences.
- **Strikes · Add**: manual strikes and reviewed imports; also authorizes `/strikes add`.
- **Strikes · Remove**: removing strikes; also authorizes `/strikes remove`.

Any of these options includes viewing history and replacements. Add does not grant removal; Settings does not grant either manual action. Select all three for full dashboard access. Discord Administrators retain access to all strike commands. Other users need the matching dashboard grant. Discord commands and account-selection buttons reread shared grants, so revoked access cannot authorize a later action. Dashboard writes also retain authentication and CSRF protections.

## Main files

- `utils/strike_store.py`: ledger, exemption rules, expiry, ranking, import preview/apply.
- `utils/strike_wars.py`: saved-war retrieval, pagination, coverage, validation.
- `extensions/commands/strikes.py`: Discord Components V2 commands and monitor lifecycle.
- `cwl_web/strikes.py`: dashboard API.
- `web/cwl/src/StrikesWorkspace.tsx`: dashboard interface.

## Operational limits

Deploy through the normal bot and dashboard services. Restart the existing bot service; do not start a second gateway process. Historical imports remain an explicit staff preview/apply action after deployment.

Archived wars are best effort, not a guaranteed 60-day history. A current roster refresh is required before replacement candidates appear. Discord display and live provider behavior still need a production smoke check after release; local UI checks use fixture data.

Import eligibility is account-based. Both ClashKing and ClashPerk are checked; an account with no owner in either successful result can receive a strike and displays Not linked. Conflicting owners or failed role checks defer only that account into Needs review, without writing a ledger record. A confirmed Discord member-not-found response means no current server roles; other Discord errors remain unknown. Provider-wide link outages still defer affected wars, preserving role exclusions. Deferred accounts must be checked again in a fresh preview before import; applying an older preview never adds newly resolved accounts without review.

CWL wars are recorded separately as informational history. They show each account's single attack used or missed, and are labeled CWL · No strikes. They never add active strikes, strike totals, expiry penalties, or replacement priority. Regular wars still require an explicit two-attack limit. CWL history is visible through Find war and All records, while the default active-strike view stays unchanged. CWL records use separate IDs and are safe to load repeatedly.

## Tracking health

The Accounts page has a compact Tracking status section. Each family clan shows its last completed check, last successful check, latest saved war, and any current problem. A failed or partial check preserves the previous successful timestamp. Old checks are shown as delayed rather than healthy; a successful check can contain no new wars. Saved error details use plain, safe messages instead of raw provider responses.

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
