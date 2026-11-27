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
The peer check alone does not distinguish a direct local caller from public
traffic forwarded by the local Caddy process. The public-proxy boundary below
is additional protection; it does not replace bridge authentication.
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
Shaka's operator record 1097 (2026-11-17) identifies the bot override as
`http://127.0.0.1:8766`, through the loopback Caddy gateway, with the backend on 8767. Keep that recorded override unchanged for Part J. The default 8767 origin
remains valid for a direct local deployment. The documentation preparation below
did not reread production service environments.

### Public-proxy boundary

The gateway log filter deletes `request>headers>X-Cwl-Discord-Secret` from every
Caddy log (added 2026-11-27). Keep it when the Caddyfile changes. Old journal
entries from before that date can still hold the current secret; rotation is
not yet done (Ruggie's choice, 2026-11-27).

The Part J gateway configuration must block `/api/cwl/discord/*` only when the
request also has a `Cf-Connecting-IP` header. Apply this AND matcher before the
backend proxy in **both** host paths: the legacy `cwl.ruggie.zone` handle and the
generic API handle. Public traffic passes through the Cloudflare edge, which
sets/replaces that header before either tunnel reaches Caddy. The direct bot
request to 127.0.0.1:8766 has no such header and must continue to reach the
backend. A local process can still reach the bridge HTTP handlers; the shared
secret and each handler's existing actor/permission checks remain required.

Every backend proxy also overwrites `X-WU-Client-IP` with
`{http.request.header.Cf-Connecting-IP}`. It must not preserve a client-supplied
value or use `X-Forwarded-For`/`X-Real-IP` as the source. A missing Cloudflare
header produces no usable client-IP value: the backend must not combine direct
local callers into a single 127.0.0.1 rate-limit bucket. A1/F and J can release
in either order, with releases kept serial.

All four authenticated bridge endpoints derive their origin from the same
`bridge_config()` contract:

| Path below `/api/cwl/discord/` | Bot caller                                                                                                                                   |
| ------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------- |
| `member`                       | `utils/cwl_member_client.py`, used by `extensions/commands/cwl_member.py` and the published-assignment read in `extensions/commands/todo.py` |
| `weight`                       | `utils/clan_weight_client.py`, used by `extensions/commands/fwa/weight_save.py` and `extensions/commands/tickets/link_account.py`            |
| `pool-roles`                   | `extensions/tasks/cwl_pool_roles.py`                                                                                                         |
| `post-updates/validate`        | `extensions/tasks/cwl_post_update_bridge.py`, used by the CWL reminder worker                                                                |

At source revision `12f8bb23719ce7ebfef56403e20c1e63e76c9439`, the complete
default URLs are:

```text
http://127.0.0.1:8767/api/cwl/discord/member
http://127.0.0.1:8767/api/cwl/discord/weight
http://127.0.0.1:8767/api/cwl/discord/pool-roles
http://127.0.0.1:8767/api/cwl/discord/post-updates/validate
```

The operator-recorded gateway URLs are:

```text
http://127.0.0.1:8766/api/cwl/discord/member
http://127.0.0.1:8766/api/cwl/discord/weight
http://127.0.0.1:8766/api/cwl/discord/pool-roles
http://127.0.0.1:8766/api/cwl/discord/post-updates/validate
```

The member and weight clients send one POST without redirects or automatic
transport retries. The pool-role worker sends its actions to the single
`pool-roles` URL; post-update scope validation uses the single
`post-updates/validate` URL. This caller inventory is a source check, not a new
bridge request or a fresh production-environment observation.

Before a J reload, validate an isolated local Caddy using the same routing rules:
each path with a Cloudflare header must return 404 on both hosts without reaching
the fixture backend; without it, each path must reach that backend. Prove the
client-IP overwrite on both proxies, including an absent Cloudflare header and
forged incoming values. Keep local proof on fixture ports, never 8766/8767.
After an approved release, use read-only public checks and existing bot journals;
do not send an extra bridge POST. The proposed Part J headers/configuration are
not release evidence until the required all-page browser checks and normal
backup, validation, review and reload steps have completed. Part J activation
remains held until the Part D production release is complete; releases stay
serial. No bot environment change or extra bridge POST is part of J activation.

### Part J headers and local verification — 2026-11-18

Ruggie's approval of 239 is recorded in Shaka 1070. D3 and D18 authorize the
gateway proposal; 1097 refines it to the Cloudflare-header AND path matcher and
the two proxy-header overwrites. The exact retained proposal has SHA256
`f4f86f4fcb8fcd852c9c349f1d73d1b07545dc3d580872ba9862a26e02b32c5a`;
the retained historical before-file has SHA256
`04629ad49237b0ec559a2a124a3891c98fb4f2df7ce130fd70e6d71c06c19cb5`.
These are reviewed local inputs, not a fresh reading of the active Caddyfile.

The proposed response headers are `Referrer-Policy: same-origin`,
`Strict-Transport-Security: max-age=31536000`, and this CSP:

```text
default-src 'self'; frame-ancestors 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https:; media-src 'self' https:; font-src 'self'; connect-src 'self'; worker-src 'self'; manifest-src 'self'; object-src 'none'; base-uri 'self'
```

| CSP source/directive                                             | Existing contract it preserves                                                                                                                                                                                             |
| ---------------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default-src 'self'`, `script-src 'self'`                        | Same-origin application entry, lazy modules and default resource boundary. No inline-script or eval permission.                                                                                                            |
| `style-src 'self' 'unsafe-inline'`                               | Same-origin stylesheets and existing React style attributes for colors, sizing, positioning and roster controls. This permits inline styles only.                                                                          |
| `img-src 'self' https:`                                          | Local branding/artwork plus existing arbitrary public HTTPS image-preview contracts, including Discord avatars/emojis, Clash badges and configured media URLs. A finite CDN list would reject already accepted image URLs. |
| `media-src 'self' https:`                                        | Existing HTTPS video previews in DiscordPreview.                                                                                                                                                                           |
| `font-src 'self'`                                                | Self-hosted WU Inter WOFF2; its Arial fallback is local. No remote-font host is added.                                                                                                                                     |
| `connect-src 'self'`                                             | Same-origin application API calls. Browser PushManager plumbing adds no application fetch origin; live push delivery remains unverified.                                                                                   |
| `worker-src 'self'`, `manifest-src 'self'`                       | Existing `/sw.js` registration and same-origin web manifest.                                                                                                                                                               |
| `frame-ancestors 'none'`, `object-src 'none'`, `base-uri 'self'` | Anti-framing requirement and restrictions on unused embed/base surfaces.                                                                                                                                                   |

No `data:`, `blob:`, remote-font host, extra API origin or `unsafe-eval` source is
added. Object-URL downloads do not require permission for blob images or workers.

Reused local evidence is the complete self-contained J294 report, SHA256
`7e906e55604b6618baec9add57a69e2dc930e36f39131f015ac45c3629141127`.
Terra299 accepted its saved/static proof; that review did not execute the browser
again. Under Ruggie's headless-fixture exception 1119 and Shaka 1130, browser
navigation used literal `http://127.0.0.1` behind isolated Caddy at 360×800 and
1440×1000. Saved runs used headless Google Chrome157.0.8103.78 through
playwright-core1.56.1, labelled fixture preview. There was no TLS/NSS trust modification, certificate exception,
insecure-origin flag or browser Host-header override in the accepted runs.

Accepted candidate coverage is **102 semantic passes and two explicit skips**:
51 passes plus the known `/server` skip at each width. The completed mobile run
uses pin `2e01272044bad39a3d5995ebf845f72a0bccdcd462c00edf4484406a314f1979`;
the final desktop run uses
`78464f62edff1100f9ab58906ee99b71b29dc37b89ab2caf9c272bdfd5f2b002`.
Five supplemental mobile panel checks and five desktop tab/panel checks passed
without captures. The mobile observer gained a panel assertion; there is no
claim that all cases ran under one observer pin or that mobile was fully rerun.

Shaka1129 keeps `/server` as an existing verification limit: the owner-allowed
view is absent from visible navigation and redirects Home. Its shared
`ServerManagement-XuvOcN2x.js` bundle was actually fetched on reachable
`/server/applications`, SHA256
`db2fb1ef0142ea28f3224329ab8d33fddebc2bcc2f4d60b15998adbdab9099ab`, with
the proposed CSP and a clean console. This verifies the shared bundle, not the
unreachable server-specific UI; the frontend guard is outside Part J.

Each accepted width had zero console/page/CSP/HTTP/abort/write error signals,
32 bridge-policy cases, all 184 main-site asset hashes matching, exact protected
SQL counts/full schema and all 75 synthetic Mongo snapshots, and owned-process
cleanup. The legacy host was checked only by HTTP Host headers: its 159 matching
and 25 nonmatching asset responses are retained comparisons, not legacy-browser
or resource-readiness passes. Accepted candidate entries used 117 finite pinned
offline image fulfillments per width with synthetic favicon bodies; this is not
live CDN, avatar or TownHall pixel verification.

The 173 original screenshots include accepted runs and preserved failed
attempts. Physical phone, assistive technology, live Discord/push delivery,
public TLS and current production behavior remain unverified by this local
evidence. This documentation-only pass reuses those results without another
browser matrix or backend suite. Activation still requires the normal verified
backup, current-head review, Caddy validation/reload and read-only public/journal
checks after Part D. Historical member-feature release notes below do not expand
that scope.

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
