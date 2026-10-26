# Discord CWL member workflow audit — 2026-10-26

## Scope and design

`/cwl-member` remains a private alternative to the dashboard. The entry keeps
Open CWL dashboard first; choosing Discord supports signup, changing pools,
withdrawal, and published assignments without opening the website.

Use the shared `GOLDENROD_ACCENT` in native Discord Components V2 containers.
Use concise action labels, explicit confirmations, and a small number of controls
per row. Discord owns button colors, typography, native select behavior and final
responsive rendering; do not promise a pixel-identical dashboard theme.

The signup journey is pool → accounts → review → save. Explain Main and Lazy
before choosing. Identify saved pools in account options and transfers in the
review. Show pagination only when multiple pages exist. Do not repeat all account
options above the same select menu. Closed seasons are view-only; an absent
member season has its own status. A changed season requires the member to review
it before starting again.

Assignments show only the current member's published snapshot. Joining
instructions are available through a separate disclosure with pagination so long
instructions remain accessible in Discord. Draft placements remain private.

## Findings addressed

- Saved-data reads unnecessarily fetched every linked player. The authenticated
  bridge now supports a strict boolean `include_accounts` option. Skipped account
  data is `not_loaded`, never a false empty result. Signup still loads current
  account facts and every save verifies ownership and policy independently.
- Unknown current-clan categories could be offered Main and rejected only at
  save. The picker now shares Main eligibility policy with the service.
- Rejecting a selection over the 100-account limit could erase prior choices.
  Rejected choices must leave the original selection intact.
- Old panels could silently enter a newly selected season. A season transition
  must clear pending choices and return to the current-season summary.
- A lost Discord edit response could strand the panel. Keep its consumed version
  and give a private reopening instruction; never replay an uncertain write.
- Joining instructions, closed-season context, and named withdrawal confirmation
  were missing or unclear. Long button groups and redundant account lists added
  unnecessary clutter on narrow screens.

## Primary research

- [Discord component reference](https://docs.discord.com/developers/components/reference):
  native container accents, Components V2 payload restrictions, select limits,
  concise action labels and one primary action per group.
- [Discord interaction responses](https://docs.discord.com/developers/interactions/receiving-and-responding):
  acknowledge within three seconds, ephemeral responses and interaction-token
  lifetime. The existing dispatcher defers component work before network calls.
- Repository standards: `dashboard-interaction-standard.md` and `cwl-design-guide.md`.

## Verification

Final results and release status are recorded below after integration checks.
Visual artifacts use fictional data and actual serialized Hikari components,
rendered in an isolated HTML approximation. They assess density and wrapping;
they are not proof of Discord's exact Android/iOS rendering or live delivery.
No real member signup changes or live test messages are authorized by this audit.

### Final audit evidence

- Full CWL, component action/dispatch, startup and shared architecture regressions:
  **822 passed**, **22 subtests passed**, one existing real-Mongo recovery drill
  skipped because its dedicated server was not configured.
- All **338 frontend tests** passed. The dashboard production build passed into
  `/tmp/cwl-member-ux-build`; no served frontend assets were replaced.
- Independent Sol review added six state-integrity and serialized-payload tests.
  Rejected >100 selections, cross-season transitions, provider outages, uncertain
  edits and old-panel conversion are covered. No concrete unresolved issue remained
  in the reviewed paths. Existing aiohttp AppKey warnings remain.
- Bridge regressions prove saved-only reads make zero player/link/family provider
  calls, still recheck server membership, and do not weaken write verification.
- Isolated visual previews at 320px, 390px and 1280px use fictional long names and
  actual serialized Hikari containers. Compact rows were revised after the 320px
  check. Native menu options are shown only in a separately labeled approximation.
- Hikari's actual REST payload builder adds `IS_COMPONENTS_V2` for containers.
  Editing an old entry also clears legacy content/embeds; a regression verifies
  the serialized request without making a Discord request.

The existing Discord command name and dashboard entry remain unchanged. The
bridge flag is additive with the old full-snapshot default, so a previously
running bot remains compatible during a web-first restart. No schema or stored
member-data migration is required. Existing sessions expire on bot restart;
opening `/cwl-member` creates a fresh private panel.

After the final two-button account-selection row adjustment, all **54 focused
member transport/service/end-to-end/red-team tests** passed (six subtests), runtime
imports passed, and `git diff --check` was clean. The separate Clear selected
control appears only when accounts are selected. The final visual fixture was
regenerated from those components.

### Release status

Automatic approval review rejected the proposed main-branch commit/push because
this new audit request did not explicitly authorize default-branch publication
under the repository's manual-deployment rules. No push, runtime-checkout update,
service restart or live message was performed. Changes are retained in a local
review branch pending explicit authorization for this release. Existing production
services were observed active at revision `5becff2` during read-only checks.

### Authorized release — 2026-10-26, 10:44 EDT

The user explicitly authorized this release after the approval block. Approval
review accepted deployment. Commit `98a665e` was fast-forwarded into main,
pushed, and installed in both clean local runtime checkouts. Web restarted at
10:44:51 EDT and bot at 10:44:52 EDT. No secrets, member records, schema or served
frontend assets were changed by deployment.

Verification: both runtime imports passed; main/origin/main/bot checkout matched
`98a665e`; both services stayed active/running with zero automatic restarts.
Post-start web and bot journals had zero ERROR/CRITICAL/Traceback lines. Local
config returned 200. Public signup and both existing entry JS/CSS assets returned
200 via curl; anonymous auth/me returned 401. Python urllib was rejected by the
public edge (403), so its response was not treated as an application failure.
Read-only Discord API confirmed `/cwl-member` registration with no default member
permission restriction. An authenticated bot-runtime bridge probe with JSON null
returned the expected 400 before any member/provider lookup or mutation.

No live test messages or real signup changes were performed. Existing panels may
expire after restart; run `/cwl-member` again to open the updated private flow.
This documentation-only follow-up needs no second service restart.

## Linked-account parity correction — 2026-10-26

A member reported seeing only one of several linked accounts. Investigation found
three Discord-only filters: snapshot lookup, picker rendering, and submit each
required the provider's optional verification flag. The dashboard has no such
requirement. This flag is separate from the provider's Discord-account link.

Discord now uses the same linked-account eligibility as the dashboard. Both
provider sources still load; unavailable upstreams remain unavailable rather than
empty. Every submit still refreshes links for the authenticated Discord identity,
rejects unlinked or removed tags, applies Main/FWA rules, and checks the selected
season, signup window, source pool, ownership conflicts and roster revision.
Provider verification metadata is retained, but does not hide linked accounts.

Regression coverage includes the real loopback bridge → command picker → save →
dashboard read path with a verification-false link; Main/FWA rejection, another
member's tag rejection, and a link removed after selection. Independent Sol tests
also cover malformed picker rows and authorization. Cross-provider contradictory
ownership records retain existing dashboard/provider handling; this correction
does not redefine the linking service's ownership policy.

Correction validation: **827 backend tests passed**, **22 subtests passed**, one
existing dedicated-Mongo recovery skip. Independent Sol audit passed, and diff
hygiene is clean. Tests are isolated; no live signup was submitted.

## Account ordering and page guidance — 2026-10-26

The picker and signup review now list highest Town Halls first, with stable tag
ties and unknown Town Halls last. Multi-select is named explicitly in the text
and select placeholder. Multi-page lists show Page N of M and explain Next page;
selections remain selected across pages. Next page is primary before the final
page; Review signup becomes primary on the final page. Reviewing early remains
available when a member has already found every account they want.

Validation: 84 command/bridge/end-to-end/component/startup tests passed, six
subtests passed. An independent Sol review found no concrete regression and
added ordering coverage for ties and malformed/missing Town Halls. A complete
three-page test verifies selecting, advancing, returning, page-only deselection,
and reviewing the preserved choices. The 320px isolated native-component
approximation was regenerated and inspected. No live signup was used for tests.

## Direct command entry — 2026-10-26

The user requested `/cwl signup`, removal of the dashboard entry gate, and no
future shared button yet. The public member-only `cwl` group contains `signup`;
it does not register or modify the retired administrator CWL group. Staff controls
remain under `/manage`. The initial response is private Components V2 loading
text before any bridge work, then becomes the existing home panel. No link or
extra click is needed. Existing owner-bound entry buttons remain compatible.
All recovery instructions use `/cwl signup`.

Validation: **107 tests passed**, six subtests passed, including command registry,
private acknowledgement before network IO, direct home rendering without links,
wrong-server rejection, retired staff permissions and component/startup suites.
Independent Sol review found no concrete issue. Runtime command synchronization
must confirm the new subcommand and removal of the old top-level command.

### 2026-10-26 — Quiet signup help footer

All campaign signup and reminder renders (Main and Lazy, including saved custom
campaigns) now append Discord small text beneath the existing dashboard link:
“Having trouble with the dashboard? Ping staff—we can help.” No alternative
command or button is advertised. The shared renderer covers previews and sends;
validation reserves space for the footer. Roster announcements remain unchanged.

Validation: 59 signup entry, sequence, delivery and dashboard integration tests
passed. Reviewed both audiences/all reminder variants, unchanged source campaigns,
one existing dashboard button, footer placement, and exclusion from roster posts.
This is a small text-only Discord change; no dashboard assets changed.

Live maintenance: verified guild and bot ownership from current-cycle delivery
receipts, then edited six existing announcements/reminders in place. All edit
requests explicitly disabled role/user/everyone/reply mentions; no new messages
were sent. Discord returned each updated footer successfully. Existing content,
images and controls were preserved. Historical prior-cycle messages were untouched.

Follow-up: added a visible separator immediately above the help footer in shared
renders and the same six live messages, with mentions disabled. The 37 relevant
entry, delivery and integration tests passed, including footer/divider ordering.
