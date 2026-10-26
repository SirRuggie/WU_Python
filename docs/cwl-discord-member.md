# CWL member access in Discord

`/cwl signup` opens the private Discord signup panel directly. There is no
dashboard link or extra entry step. Opening the command does not create a signup,
publish a shared button, or alter announcement/reminder campaigns. The public
`/cwl` group contains only the member `signup` subcommand. Staff tools remain under
`/manage`; the retired staff CWL group is not registered.

This replaces `/cwl-member` as of October 26. Previously sent owner-bound entry
buttons still work, but this change does not create or configure a future button.
Older release notes below refer to the command name at the time of those releases.

The alternative supports Main/Lazy signup with linked accounts, review
and confirmation, saved-signup pool changes/withdrawal, and the member's published
clan assignments. Account controls paginate. Sessions expire after 12 minutes and
are discarded on bot restart; rerun the command to start again. Unsaved selections
are intentionally temporary. Saved signups use the dashboard's authoritative data.

## Ownership and persistence

`extensions/commands/cwl_member.py` owns Discord transport and temporary selections.
`utils/cwl_member_client.py` makes one authenticated request to the local dashboard
process. `utils/cwl_member_service.py` owns shared member rules, with the existing
Store and public providers injected. `cwl_web/discord_member.py` owns bridge HTTP
authorization/adaptation. The existing dashboard Store remains the only durable
storage owner. There is no second signup database or schema migration.

Do not open the dashboard SQLite file from the bot. Production recovery uses a
single writer lease and Mongo-protected checkpoints. Both member interfaces run
mutations through the same shared service inside that writer process, preserving
roster audit, placement clearing, kept-flag removal and staff change alerts. No
notification is sent by this flow.

The bridge requires an actual loopback TCP peer and a dedicated shared secret.
It rechecks Warriors United membership through Discord REST for every request;
OAuth is not used. Discord components additionally bind the invoking member,
server, expiring session and component version. Writes require the reviewed
season, roster revision and source pool where applicable. A concurrent dashboard
edit causes a conflict and a fresh review rather than overwriting reviewed data.

Only publication snapshots joined to the member's current account ownership and
pool supply clan assignments. Working placement and kept status are never returned.
A link/player provider outage is distinct from an empty account list and cannot
wipe saved signups. Current FWA accounts cannot enter Main; unknown current clan
category fails closed for Main while Lazy remains available.

Confirmations are consumed before sending a write. The client does not follow
redirects or retry requests. If delivery or its response is uncertain, check
**My signups** before making another change. A cancellation after dispatch cannot
prove the server did not commit. No notification retry is involved.

## Release configuration

Configure the same new random secret of at least 32 characters as
`CWL_DISCORD_BRIDGE_SECRET` in the bot and dashboard service environments. Keep it
out of source, command output and logs. The dashboard also needs its existing
`DISCORD_TOKEN` for fresh server-membership checks and its existing account/Clash
provider configuration.

The bot uses `CWL_DISCORD_BRIDGE_URL=http://127.0.0.1:8767` by default. Override it
only with an HTTP loopback IP origin at the dashboard's actual local port. Hostnames,
external origins, credentials, paths, queries and redirects are rejected. Both
processes must share the loopback network namespace. Missing/weak configuration
leaves the Discord alternative unavailable and keeps the dashboard link usable.
Block `/api/cwl/discord/member` in the public reverse proxy as defense in depth;
the shared secret is required even for requests forwarded by a local proxy.

Integrate this change against current main before release; this worktree began at
`77a7ecd` (including `7118462`). Deploy the dashboard service and bot together after
configuration. Command discovery finds the new module automatically; Lightbulb
registers `/cwl-member` on bot startup. Verify registration, startup imports,
service health and the pushed revision during an authorized release. Do not deploy
this worktree over newer production work. No deployment or live command
registration was performed during implementation.

## Verification

Implementation verification uses temporary SQLite databases, isolated loopback
HTTP servers and simulated Discord interactions. These checks do not prove live
Discord command delivery, physical mobile rendering or screen-reader behavior.
No real signups, live messages or published production assignments are used.
Detailed final results are recorded below after integration review.

Final integration checks (2026-10-25):

- 797 CWL, component-dispatch and startup regressions passed; one existing
  real-Mongo recovery drill was skipped because `CWL_RECOVERY_MONGOD` was not configured. The 16 subtests also passed.
- All 35 new feature tests passed after the last ownership/recovery additions.
  These cover temporary SQLite plus real loopback HTTP, controller-to-dashboard
  save/read/change/withdraw consistency, stale dashboard revisions, Main/FWA and
  Lazy policy, verified ownership, closed/hidden seasons, publication privacy,
  provider failures, duplicate/uncertain saves, cancellation, expired sessions,
  malformed category data and member-season changes during selection.
- `./.venv/bin/python tools/check_war_reminders.py` passed: 186 backend tests,
  one existing skip, 32 frontend tests, production build and diff hygiene.
- All 338 dashboard frontend tests passed. No dashboard layout was changed.
- Command auto-discovery and runtime import succeeded without a Discord connection.
- A fresh Luna agent independently reviewed the integrated implementation and
  added regression coverage. Findings resolved included Hikari select construction,
  category-outage Lazy fallback, UTF-16 emoji label limits and stale-season
  selection reset. No concrete unresolved finding remained in the final checks.

Usability/accessibility scope: reviewed native labeled buttons and selects,
private responses, explicit confirmations and cancellation, 15-account/5-assignment
pagination, complete links, plain status/error copy and UTF-16 component/message
limits using isolated fixtures with long/emoji/external-looking names. Native
Discord controls own responsive layout, keyboard focus and touch targets; no
live Discord message was sent, so mobile/desktop rendering and assistive technology
were not visually verified. Existing aiohttp AppKey/deprecation warnings remain.

The broad suite exposed a pre-existing scheduler test tied to September 2026; its
clock is now explicitly frozen to that intended month. Account-provider fixtures
now include realistic clan category fields to exercise fail-closed Main eligibility.

## Independent Sol review and release handoff

At the user's correction, a fresh `gpt-6-sol` agent independently reviewed the
completed implementation at `0fa686f`. This is the final requested independent
review; the earlier Luna review remains historical evidence, not a substitute.

Sol reproduced and the orchestrator resolved two findings:

- The pool-change review screen lacked its Confirm controls, and Cancel/Keep
  signup did not navigate back. The screen now renders Confirm pool change,
  Back and Cancel; returning to the saved signup clears the pending destination.
  A rendered Move → Confirm regression proves one submit and rejects reuse of
  the old confirmation. Navigation itself makes no write.
- Discord's assignment list included signups added after the latest publication
  as pending rows. Discord now selects only matching publication-account rows.
  The dashboard deliberately retains its existing pending-row presentation.
  Both paths still require current owner/pool matches for published placements;
  draft roster data remains excluded.

Sol added four independent regressions in `tests/test_cwl_member_sol_review.py`
and reported no remaining concrete finding in the inspected paths. Final full
CWL/component/startup suite: **804 passed, one skipped, 16 subtests passed**.
The skip is the isolated real-Mongo recovery drill requiring
`CWL_RECOVERY_MONGOD`. The required war-reminder gate passed again, including
**186 backend tests**, **32 frontend tests**, production build and diff hygiene.
Existing aiohttp warnings remain. Tests used isolated fixtures and loopback HTTP;
no live Discord delivery, mobile rendering or production startup was validated.

The user subsequently authorized deployment, but automatic approval review
rejected production pull/restart actions under the repository's manual-deployment
instruction. No production configuration, services or member records were changed
by this review. Code is ready for integration and operator release after that
approval block is resolved, with the normal runtime checks still outstanding.
See [operator release commands](cwl-discord-member-release.md). The current web
service uses port **8766**, so the bot must override the default bridge origin to
`http://127.0.0.1:8766`. The shared secret has not yet been provisioned.

## Authorized deployment — 2026-10-25, 21:03 EDT

The user explicitly renewed deployment authorization after the earlier block.
Approval review accepted the deployment actions. Release `c81a070` was
fast-forwarded into main and pushed; both clean production checkouts were updated
without force or replacing newer changes. The dashboard was at `77a7ecd`; the bot
was at ancestor `287d8b1` and also received the intervening main changes.

A fresh shared secret was installed without disclosure in the dashboard private
environment and bot `.env`. The bot bridge origin is `http://127.0.0.1:8766`.
Private configuration backups are dated `20261026T010325Z`; the bot backup is under
its ignored `.local/` directory, and the dashboard backup remains under `.local/`.
No schema or member-data migration was performed.

Both runtime import checks passed. The dashboard user service restarted at
21:03:46 EDT and system bot service at 21:03:47 EDT. Both remained active/running
with zero automatic restarts. Post-start logs showed successful Mongo restore,
no tracebacks and no ERROR/CRITICAL entries. The pushed main revision and both
runtime checkout HEADs matched `c81a070` at verification.

Live read-only checks confirmed:

- Global Discord slash command `cwl-member` is registered (type 1), with null
  default member permissions rather than administrator-only restrictions.
- A bot-runtime request using the configured shared secret reached bridge
  validation and returned the expected 400 for JSON `null`, before identity
  lookup, provider access or writes. This verifies matching runtime secrets.
- Local dashboard config and public `/signup` returned 200; anonymous
  `/api/cwl/auth/me` returned 401.
- Served entry assets `index-xJ_Ye5GU.js` and `index-CIbS_aXo.css` returned 200.
  Existing served assets were retained; this feature changes no frontend source.

No live test messages were sent and no real signup was changed. Command
registration and service health are verified; a real member's interactive signup
and physical mobile rendering were not exercised. A documentation-only follow-up
records this evidence without requiring another service restart.
