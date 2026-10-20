# Account strikes

Implemented for the Warriors United Discord bot and its existing dashboard. This document describes the new system; `botghost-strike-sentinel-investigation.md` describes the old BotGhost reference.

## Rules

- Track registered family clans together, including FWA.
- Only complete, ended, regular wars with an explicit two-attack limit qualify. CWL is deferred.
- Both attacks missed: one strike. One missed: history only. Both used: no strike.
- Strikes belong to the player tag. Member lookup includes linked accounts. Moving clans does not clear history.
- Active strikes expire 90 days after the war ended, or after a manual strike was added. Expired and removed records remain available.
- No automatic punishment.

## Staff workflow

The **Strikes** dashboard has History, Replacements, Leave, Exempt roles, and Import wars tabs.

History supports player, Discord member, clan, and status searches; add a manual strike with a reason, or remove a strike with a reason. Choosing a member lets staff choose the player account.

For FWA recruitment, enter the recruit's weight. Results prioritize marked fillers, then most active strikes, then closest weight. Filler preference belongs to the selected clan. Accounts without a usable weight cannot be ranked. Existing roster weights and manual weight overrides are reused.

Leave starts when approved and resumes tracking at **00:00 UTC on the selected date**. All currently linked accounts are selected initially; staff can uncheck individual accounts.

Role `769130325460254740` is excluded by default. Staff can change the list in Exempt roles. Current role membership is used for imports; historical role membership cannot be reconstructed. Missed attacks for exempt accounts are recorded without adding a strike. Unknown roles or conflicting/unavailable links defer processing.

Discord commands use private Components V2 responses: `/strikes view`, `/strikes add`, `/strikes remove`, and `/strikes replacements`. Leave, exempt roles, filler preferences, and import review are managed in the dashboard.

## Import and monitoring

Check past wars to preview up to 90 days of available saved history. Review incidents, uncheck unwanted records, then import. Availability depends on the external archive. The interface reports coverage and unavailable clans; incomplete or ambiguous wars are skipped rather than guessed.

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

Archived wars are best effort, not a guaranteed 90-day history. A current roster refresh is required before replacement candidates appear. Discord display and live provider behavior still need a production smoke check after release; local UI checks use fixture data.
