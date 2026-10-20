# Strike Sentinel: BotGhost investigation

Inspected: October 20, 2026  
Source: signed-in BotGhost dashboard, **Strike Sentinel**  
Purpose: document the old system before rebuilding its strike features in Warriors United.

## Plain-English overview

Strike Sentinel is a Discord strike ledger for Clash of Clans players. Staff can issue strikes manually or run a command that checks a clan's war for missed attacks. It looks up players and linked Discord accounts, applies clan-specific exceptions and weights, saves records, and displays histories.

**The supplied share code `CMD_7e48ee89-eee2-4dae-801a-ca86f8492df4` belongs to `/set strikes`.** Verified through its existing Copy Share Code control.

War scanning is staff-triggered. No custom timer was found that automatically scans wars or expires strikes. The separate standard moderation module must not be confused with the custom Clash strike ledger.

## Scope and confidence

Inspected all 16 custom command canvases, the sole custom event, storage inventory and scopes, timed-event settings, and relevant enabled modules. Examined selected block settings, permissions, and message templates. The dashboard showed the bot online with Unlimited Premium.

This is a **configuration audit, not a live execution test or complete source export**:

- No strike, reset, API test, or punishment was executed.
- Historical member records were not exported. This documents behavior and structure, not every saved strike.
- External Worker/Supabase source was unavailable. Exact contracts and internal behavior remain unverified.
- Some previews truncate expressions and URLs. Ellipses below reproduce that limitation.
- Old/prototype blocks coexist with current workflows. Rendered edges did not yield a reliable complete execution graph; presence alone does not prove execution.
- Only `/add-strike` permissions were inspected in detail. Other permissions and Discord-side overrides remain to be checked.
- Opening some settings caused BotGhost to mark normalized settings as changed without an intentional edit. Observed changes were undone/discarded; one undo was followed by an automatic save of the restored state. No intentional behavior change was made, but this was not a guaranteed zero-write session.

These findings support a rebuild specification, but do not establish exact parity with every hidden setting or external service.

## 1. Custom command inventory

**16 commands: 10 enabled, 6 disabled.** Node counts include options, conditions, branches, and prototypes, not just actions.

| Command | Enabled | Nodes | Observed purpose |
|---|---|---:|---|
| `/set strikes` | Yes | 536 | Check a clan's war and record missed-attack strikes |
| `/add-strike` | Yes | 405 | Manual issuing by player tags or Discord member |
| `/view strikes` | Yes | 309 | Member/player/all-user history |
| `/clear strikes` | Yes | 33 | Broad reset of strike data and related settings |
| `/set strike-options` | Yes | 846 | Leave, exemptions, weights, clan configuration |
| `/set asset` | Yes | 12 | Arrow/footer assets |
| `/view clans` | Yes | 157 | Paginated stored clan selector |
| `/clear collection` | Yes | 4 | Empty ignored-clan collection |
| `/beta-strike` | Yes | 400 | Alternate manual strike workflow |
| `/beta view-strikes` | Yes | 435 | Extended clan/server history and date-sort service |
| `/set emoji` | No | 7 | Town Hall emoji mappings |
| `/clear on-leave` | No | 6 | Clear selected member's leave variable |
| `/paginate` | No | 126 | Generic five-item-per-page display prototype |
| `/backup view-strikes` | No | 211 | Older history/report implementation |
| `/test add-strikes` | No | 210 | Earlier manual strike/account-selector experiment |
| `/menu paginate` | No | 115 | Generic paginated select-menu prototype |

Groups: Strike Commands (5), Tools (2), Ungrouped (9).

## 2. `/set strikes`: bulk war scanning

Despite its generic description, this is the main war-analysis workflow.

### Selection and lookup

1. Remember the invoker's Discord ID.
2. Build a clan selector from stored ClashKing names/tags, with next/previous pages.
3. Ask for confirmation of the clan.
4. Offer optional `skip-opted-out` input.
5. Request war data from `https://api.clashk.ing/war/%23{strike_c…`.
6. Use `ck_war.response.0`, the first returned war.
7. Determine which side is the selected clan; extract its roster and opponent.
8. Convert preparation/end timestamps to Unix time.
9. Iterate members and inspect attack counts.
10. Fetch player data and Discord links. Unlinked accounts use `Not Connected`.

Fewer than two attacks is a candidate offense. Missing/absent attacks are treated as two missed attacks; one recorded attack means one missed attack. This assumes a two-attack war. No separate one-attack CWL ruleset was identified.

### Exceptions and context

Checks include ignored Discord users, ignored roles, TH at/below the clan threshold, active leave, current/historical war preference, and whether the player remains in the clan.

Historical data comes from `https://api.clashk.ing/player/{p_tag}/h…`. Preference-change timing is compared with preparation/war timing. Notes distinguish opting out before preparation or during preparation/war, and `Not in Clan`.

**Potential mismatch:** the input is `skip-opted-out`, while conditions reference `{option_skip-opted-outplayers}`. Intended opt-out skipping is not proven to work.

### Weighting

| Mode | Intended behavior visible in the canvas |
|---|---|
| `war` | One strike for the missed-war incident |
| `attack` | Weight by missed attacks: one or two |
| `user` | Group linked accounts under the Discord member |

TH scaling can reduce the two-missed-attacks weight for lower THs. The `user` path tracks struck users, linked strike IDs, primary-ID notes, and wording equivalent to “2 Missed Attacks — 1 Strike (All Accounts).” Mixed-account cases require execution testing.

### Recording and reporting

- Write attributes into separate BotGhost objects keyed by strike ID.
- Store target, player name/tag/TH, clan, reason, weight, issuer, time, opponent, and notes.
- Update member strike collections/counts and the server counter.
- Assemble the run's new strike-ID range into report data.
- POST to `https://th-sorter.shaun-m-bridges.worke…`.
- Format users/accounts with TH emojis, player links, weights, IDs, reasons, and notes.
- Build one-missed-attack and two-missed-attack report sections across several pages.
- Send channel reports and an informational summary; delete loading messages.

The canvas has a fixed 50-iteration report-building loop, explicit account positions 0–9, and bounded page branches. Test those limits. No dependable “war already processed” guard was established; reruns may duplicate records unless an unverified path prevents it. No transaction spans the separate writes.

## 3. `/add-strike`: manual issuing

### Verified settings and inputs

Server-only; replies visible to the command user; allowed role **Family Lead**; no banned roles/channels or extra required permissions shown; no cooldown. This does not establish other commands' permissions.

| Input | Required | Meaning |
|---|---|---|
| `reason` | Yes | Free-text reason |
| `player` | No | Comma-separated tags |
| `discord-user` | No | Member whose linked accounts should be offered |
| `strike-weight` | No | Numeric weight, two configured choices |

Omitted weight defaults to **1**. Exact labels/values of the two choices were not opened.

### Execution design

1. Show loading and remember the invoker.
2. Select/confirm a clan.
3. For tags: iterate, trim spaces, remove `#`, request player/link data.
4. Otherwise retrieve the selected member's accounts and show a paginated selector.
5. Neither target input follows an error path; no accounts follows a No Inventory path.
6. Confirm or cancel the selected account.
7. Check ignored users, ignored roles, TH exemption, and active leave.
8. Offer **Yes/No overrides** for exceptions.
9. Write strike attributes, append ID to the member's list, add weight to their total.
10. Send confirmation and increment the server strike-ID counter.

Requests include `GET https://api.clashk.ing/v1/players/!{p_tag}`, a `/v1/clans/!…` lookup, and member/tag linking POSTs to `ckrelay.shaun-m-bridges.workers…`.

The gold **Strike Issued** embed includes Discord mention, TH emoji, linked player name, tag, weight, ID, date, reason, issuer, and footer image. Player links use `https://p.clashk.ing/`.

War preference is read, but direct manual rejection based solely on it was not established. The TH check references `{p_th}`; the fetched TH is stored, but an assignment to `p_th` was not established. Verify this exemption.

Separate write/confirmation/counter blocks can fail partway through. No rollback was identified.

## 4. History viewers

### `/view strikes`

- Optional member or player-tag filter; both together lead to an error path.
- Neither filter gives all-users history.
- Remove `#` from tags; examine IDs newest first.
- Accumulate records and POST to `view-strikes.shaun-m-bridges.wo…` for grouping/transformation.
- Format users/accounts and notes; main output goes to the channel.
- **7 items per page**; first/previous/next/last controls and page-jump modal.
- Validate page bounds; disable endpoint controls.
- Navigation checks the interacting user against the original invoker.
- Includes an emoji legend.

Older simple-display blocks and hard-coded prototypes remain on the canvas. They are not automatically requirements to preserve.

### `/beta view-strikes`

- Same BotGhost ledger.
- Adds `clan-strikes` and `server-strikes` alongside member/tag options.
- Counts selected options with zero/one/multiple-selection branches.
- Clan selection/confirmation and filtering by stored clan tag.
- Uses `view-strikes-datesort.shaun-m-b…`.
- **10 items per page**, similar navigation.

The service name suggests date sorting; exact order/tie-breaking needs source or sample results.

**Correction to an earlier investigation update:** beta commands were not shown to be a new database-backed system. They still use BotGhost storage. Supabase blocks elsewhere do not establish otherwise.

## 5. `/set strike-options`

### Leave

Select a member, enter start/end in `YYYY-MM-DD`, convert both with **23:59:59**, save leave/return/`on_leave=true`. Checks compare current Unix time with the bounds.

The start is at the end of the entered day, not its beginning. No cleanup timer was found. The flag can remain true after return while the date check stops treating the member as away. Define timezone and inclusive dates explicitly in a rebuild.

### Ignored users/roles

View/add/remove clan exceptions. Duplicate-add checks, confirmation/cancel controls, invoker checks, temporary selections, and list rebuilding are present. Menus have bounded selection, including 25-item handling.

### TH and weight configuration

Configure/remove TH ignore threshold; choose `attack`, `war`, or `user`; configure/remove TH scaling. The exemption comparison is at/below the threshold.

### Advanced clans

- Refresh server-linked clans from `https://dev.api.clashk.ing/v2/link/serv…`.
- Rebuild parallel name/tag lists and a clan-name lookup object.
- Exclude by name-containment setting and explicit ignored-tag collection.
- Add/remove ignored clans and rebuild lists.
- Refresh includes a server-owner ID check.
- A final plain-text placeholder says `UPDATE ME`.

### Supabase uncertainty

Add Ignored Users/Roles request blocks POST to `https://rhwubtryeomvgsmkedaq.supabase.c…`. Bodies, credentials, schema, and active-menu reachability were not verified. Their presence does not prove an active production dependency.

## 6. Resets, utilities, and experiments

### `/clear strikes`

A broad reset, **not single-strike removal**. It clears/reset variables for counter, totals, reasons, targets, times, opponents, player name/tag/TH, issuer, member strike lists, clan name/tag, clan-ID index, ignored users/roles, clan struck users, leave, TH exemptions, weight mode, weights, TH scaling, temporary collections, notes, linked IDs, and struck-user counters.

A confirmation reply exists; a protective pre-reset confirmation was not established. Every deletion block's per-member targeting was not inspected. Rebuild as separately scoped revoke-one, clear-member, reset-history, and reset-settings operations.

### Other enabled commands

- `/set asset`: required key/value; choose arrow/footer; set property, reply, remove menu.
- `/view clans`: paginated clan selector, process selected tag, reply. `{items_select}` needs validation against actual menu output.
- `/clear collection`: empty ignored-clan collection; builder indicates no reply.
- `/beta-strike`: same ledger, APIs, selectors, exception prompts as manual issuing. Main `/add-strike` has an extra Correct Clan confirmation group absent from the beta's matching node set. Beta naming does not prove completeness.

### Disabled commands

- `/set emoji`: name/emoji-ID inputs, set TH emoji property, reply.
- `/clear on-leave`: optional user, delete Player On Leave, reply; validate optional targeting.
- `/paginate`: `BGVAR_items`, five per page, navigation/page-jump form.
- `/menu paginate`: `BGVAR_items` menu; navigation consumes slots, offsets advance 24 initially and 23 later.
- `/test add-strikes`: earlier manual issuing/account selector with public selection output.
- `/backup view-strikes`: older grouped report with explicit account slots, reason sections, several pages.

## 7. Events and scheduling

The sole enabled **custom event** has six nodes. On reaction added, it checks emoji ID `1373049937050341466`; a match sends literal **`ZXV`** to that channel. No strike writes or additional user/channel restriction were visible.

Timed events list **Rotating Status Handler**, every **30 seconds**. Displayed timezone: **(GMT-11:00) Midway Island**. Default server: Select Server. Actual status: **Fixed**, **Watching**, **`from the shadows...`**. Status handlers cover startup, dashboard update, and rotating status.

No custom war-scan or strike-expiry timer was listed.

## 8. Other enabled modules

Navigation marked Custom Commands, Custom Events, Message Builder, Timed Events, Data Storage, Moderation, Transcripts, IFTTT, and Status enabled.

### Moderation

The standard module offers bans add/remove/temp; timeouts add/remove; kick; warn; roles add/remove/temp; voice deaf/undeaf; cases view/remove; notes add/remove/view; history/clear-history; slowmode; purge; nickname; channel lock/unlock; ping; server-info; say.

Settings cover permissions, admin/moderator roles, logging, DMs, and automatic punishment. **3 warnings → 1h timeout appeared in the new-rule editor, not as a verified saved rule.** Do not report it as active.

Handlers: Moderation Handler (variable changes), Temporary Role & Ban Check (timed event). Internal module workflows/per-command switches were not fully audited. No connection to custom `user_strike_count` was established.

### Other observations

- Transcripts: **No Transcripts Yet**.
- IFTTT: Services section without configured entries in the inspected view.
- Message Builder: enabled; full reusable-template catalog not audited. Custom commands embed their own message definitions.

## 9. Storage model

**52 custom variables**, **22 module variables**, **5 unused custom variables**. Types: 1 text, 2 numbers, 14 collections, 35 objects.

### Strike-record join

Separate server-scoped objects share strike ID as the property key:

| Suffix after `BGVAR_` | Meaning |
|---|---|
| `strike_reason` | Reason |
| `strike_target` | Member ID/unlinked marker |
| `strike_time` | Unix timestamp |
| `strike_opponent_war` | Opponent |
| `strike_player_name` | Player-name snapshot |
| `strike_playertag` | Player tag |
| `strike_player_th_level` | TH snapshot |
| `strike_issuer` | Staff issuer |
| `strike_user_clan` | Clan-name snapshot |
| `strike_user_clan_tag` | Clan tag |
| `strike_user_weight` | Weight |
| `strike_user_notes` | Context |

Server `strike_id_counter` supplies IDs. Member `user_strikes` stores IDs; `user_strike_count` stores weighted totals. Record count and sum of weights differ.

### Complete custom-variable inventory by scope

Names omit `BGVAR_`.

**Shared per server**

- Number: `strike_id_counter`.
- Collections: `ck_clan_name_list`, `ck_clan_tag_list`, `ignore_clan_collection`, `struck_users`, `temp_all_strikes`.
- Objects: `strike_reason`, `strike_target`, `strike_time`, `strike_opponent_war`, `strike_player_name`, `strike_playertag`, `strike_player_th_level`, `strike_issuer`, `strike_user_clan`, `strike_user_clan_tag`, `clan_ignored_users`, `clan_ignored_roles`, `clan_striked_users`, `clan_th_ignore_level`, `clan_strike_weight`, `strike_user_weight`, `strike_user_notes`, `ignore_clan`, `ignored_clan_name`, `strike_ids_by_clan`, `strike_weight_by_th`, `clan_name`.

**Per member per server**

- Number: `user_strike_count`.
- Text: `view_strikes_collection`.
- Collections: `user_strikes`, `menu_selected_ignored_users`, `menu_selected_ignored_roles`, `menu_selected_user_accounts`, `ec_inv`, `user_strike_data`, `menu_selected_user_accounts_2`, `view_strikes_selected_options`.
- Objects: `player_on_leave`, `struck_user_ids`, `menu_ignored_users`, `menu_ignored_roles`, `menu_user_accounts`, `menu_user_accounts_2`, `struck_user_id_count`, `strike_linked_ids`, `pagination`, `select_menu_items`.

**Shared across all servers**

- Objects: `asset_arrow`, `asset_footer`, `emoji_th`.
- Collection: `items`.

Unused: `menu_user_accounts`, `menu_selected_user_accounts`, `ec_inv`, `menu_user_accounts_2`, `menu_selected_user_accounts_2`.

### Migration implications

Include guild ID in keys; preserve member/guild identity and historical snapshots; reconcile weights/totals; avoid double-counting linked records; preserve global versus guild asset scope. Server-shared `temp_all_strikes` can collide between runs. Member-scoped pagination/menu state can collide between that member's simultaneous sessions.

## 10. External services

| Service | Role | Unverified aspects |
|---|---|---|
| BotGhost | Runtime/storage/UI | Live execution |
| Discord | Members/roles/messages | Complete overrides |
| ClashKing API | Players/clans/wars/history | Health/responses |
| ClashKing development API | Server-linked clans | Full URL/authentication |
| `ckrelay.shaun-m-bridges.workers…` | Account linking | Code/contracts |
| `th-sorter.shaun-m-bridges.worke…` | War-report transformation | Internal rules |
| `view-strikes.shaun-m-bridges.wo…` | History transformation | Internal rules |
| `view-strikes-datesort.shaun-m-b…` | Beta history transformation | Sorting semantics |
| `rhwubtryeomvgsmkedaq.supabase.c…` | Ignored-user/role request blocks | Active use/schema |
| `p.clashk.ing` | Player links | Presentation only |

Ellipses are truncated UI previews, not complete URLs to use in code. No secrets/authorization headers are included.

## 11. Findings to resolve

| Finding | Evidence | Rebuild implication |
|---|---|---|
| Shared command is war scanner | Code verified | Preserve main workflow |
| No expiry job identified | Custom events/timers | Explicit expiry design |
| No punishment tied to custom totals identified | No connection established | Choose consequences |
| Reset mixes history/settings | Clear canvas | Separate operations |
| Opt-out name mismatch | Input/condition names | Fix/test |
| Possible TH variable mismatch | Assignment not established | Validate exemption |
| Shared temporary state | Storage scopes | Invocation-specific state |
| Non-atomic writes | Separate blocks | Transaction/idempotency |
| Duplicate war processing possible | No dependable guard identified | Unique incident key |
| Leave starts at end of day | Date conversion | Explicit timezone/inclusivity |
| Two attacks assumed | Comparisons | One-attack/CWL handling |
| Fixed report limits | Loops/account slots | Generalize pagination |
| Opaque Workers | Request blocks only | Obtain source/contracts or replace |
| Permissions incomplete | Manual command inspected | Permission matrix |

### Dashboard warnings

Data Storage showed **9 things will not work**:

- Missing `BGVAR_clan_logo` in `/set strikes`, `/set strike-options`, `/add-strike`, `/beta view-strikes`.
- `clan_name` versus `BGVAR_clan_name` warnings in `/set strikes`, `/add-strike`, `/backup view-strikes`, `/test add-strikes`, `/beta-strike`.

Missing logo is supported by the inventory. `clan_name` warnings may be false positives because execution-local variables exist. Do not blindly add `BGVAR_`.

## 12. Existing Warriors United code

`extensions/commands/setup/recruit_strikesystem.py` supplies rules and acknowledgement-role behavior. Policy text mentions four strikes, 12-hour ticket deadline, mostly per-account treatment, maximum offense per incident, generally 60-day expiry.

Those are policy statements, not proof BotGhost enforces them. Existing Python/Hikari/Lightbulb, MongoDB, account linking, and tickets make a native rebuild feasible. No implementation/deployment was performed.

## 13. Rebuild scope and decisions

### Preserve

Manual issuing, staff-triggered war review, clan/account selection, exemptions/leave, TH rules/weights, account grouping, complete records, member/player/clan/server views, paginated reports.

### Decide before building

1. Manual scans, scheduled scans, or review queue before issuing?
2. Offenses/weights, including CWL?
3. Thresholds per account, member, or both?
4. 60-day expiry and exceptions?
5. Notifications, roles, tickets, removal, or staff review at thresholds?
6. Who can issue, override, revoke, adjust, reset?
7. Member DMs and staff audit log?
8. Appeals/revocations retaining history?
9. Import existing history or start clean?
10. Which beta viewer features become standard?

### Inferred engineering requirements

Coherent strike records; guild configuration; per-invocation state; war deduplication; explicit permissions; bulk preview/confirmation; auditable revocations; robust pagination; recoverable failures; validated weights/dates; explicit API-unavailable and unlinked-account behavior. These are proposed improvements, not existing features.

## 14. Evidence still needed for exact parity

- Worker source or request/response examples.
- Supabase schema only if active and wanted.
- Remaining permissions and Discord overrides.
- Defaults/live clan settings to preserve today's precise configuration.
- Existing records export to preserve history.
- Controlled tests of manual/bulk issuing, exemptions, grouping, beta ordering.
- Full truncated expressions/URLs where exact parity matters.
- Internal standard-module workflows if unrelated features are also being rebuilt.

No production command execution, historical migration, implementation, or deployment was performed.
