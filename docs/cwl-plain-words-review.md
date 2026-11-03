# CWL plain words review (119)

Release is held. This is a frontend wording sweep plus the explicitly requested
tour-numbering correction. No production data or provider/API probe is used.

## Preserved terms and boundaries

- `Main CWL`, `Lazy CWL` and the FWA sentence remain per owner 378. Exact rule
  descriptions use the supplied Main/Lazy lines. Every tour title/text stays
  verbatim; only card ordinals and their total change. The original eight decorative groups
  retain their layout and advances through explicit `progressGroup` data.
- The compact workflow strip retains visual `My clan`, `Build`, `Finalize` and
  `Announce` for 320 px widths, with full accessible destination names. All page
  headings, other links and navigation use their complete names.
- `unassigned`, `over_capacity`, `capacity`, `assigned_clan_tag` and similar
  transport/status keys, function/variable names, selectors and CSS classes are
  preserved. This is not a schema or string-variable rename.
- The legacy server-message comparison in `RosterAccountCard` retains its exact
  old capacity/Clan settings text solely to suppress a duplicate server reason.
  It is not rendered. Raw upstream errors and saved staff/Discord content are
  not rewritten or falsely relabelled.
- Family-clan `Clan settings`/history and global Staff overview are separate from
  CWL Hosting clans. Their accurate feature names stay. `Show my clans`, `Open
Clan` and task/war `View clan ...` links name other destinations, not My clan
  assignments.
- Staff publication version/history and saved roster-image versions remain
  operational evidence. Member assignment version detail is removed; staff
  `Not published yet`, publish confirmations and `Unassign from clan` verbs
  retain their distinct meanings. Staff states are called Unplaced.
- Player-tag-only lookup actions and player-only/clan-only searches retain
  specific labels; `Find a player or clan` is used only where both actually
  match. StaffSignupControls matches account name, tag and current clan, so its
  account picker uses that combined label; tag-only lookup actions stay specific. Native month-edit inputs and request/CSV/Discord values stay raw; only
  the visible Results/Bonus month labels are formatted.
- Existing linking controls say Link an account. Empty assignments offer only
  Signup for CWL under later review 137, item 6; no new help, account request or
  inference of missing links is introduced. No new controls are needed.
- Staff-only Home weight and polling controls remain for existing editors;
  ordinary members omit them. The 30-second polling logic and manual Refresh are
  unchanged. Non-CWL sign-in branding and isolated fixture warnings remain.

## End-to-end review

Check member versus editor display, unknown/failed/empty/partial data, closed
signups, waiting and provisional assignments, published/hidden staff rosters,
raw error discoverability, HTML/mention rendering, and partial weight counts.
Keep API/fetch arguments and existing link destinations identical, preserve
confirmation/discard flows, and verify all 13 tour cards without any request.
Use isolated member/staff data at 320 px and 1440 px; inspect longer headings/buttons,
no horizontal overflow, touch targets, keyboard focus and Back. These checks do
not prove real Discord delivery or assistive-technology coverage.

Final frozen runtime `5a49d7e` passed 1,555 frontend tests in 268 files,
TypeScript and production build. Four genuine assertion mutants were killed:
repeated tour five, thirteen decorative dots, raw Bonus month and member-only
weight visibility. Source was restored before the final full run. An initial
raw-month mutant selected no test and is not counted.

Real Chrome checked 22 isolated page/panel cases at 320 and 1440 px: member Home,
Signup, My signups, assignments; staff Build, Finalize, Announcements, Results,
Bonus, Signup reminders and Hosting clan settings. No horizontal overflow,
browser errors or post-login writes occurred; staff rows stayed identical and
Escape closed the clan panel. Another 26 cases walked every tour card at both
widths: thirteen unique ordinals, eight original groups, original routes/practice,
footer fit and unchanged narrative text. Narrow Signup, assignments and clan
settings, wide Build and tour images were visually reviewed. Confirmation
cancellation remains covered by component regressions, not browser submission.

The initial thirteen-dot interpretation overflowed the narrow footer and was
corrected to the approved eight-group layout. Stale copy assertions and one
negative-assertion replacement were corrected before final pass; initial logs
remain. Semantic TypeScript AST comparison pins unchanged fetch/API arguments
and existing link destinations across 39 runtime files. Backend and CSS are
unchanged. Existing large-chunk build warnings remain outside this scope.

Evidence: `.local/p119-ready-evidence.json`, `.local/p119-layout/`,
`.local/p119-tour-browser-groups.log` and `.local/p119-api-proof.json`. These are
local fixture checks, not deployment, live Discord delivery or full assistive
technology coverage. No backend full suite was repeated for this frontend-only
wording and explicit tour-counter change. Release remains held.

## Review 147 follow-up

The original 119 custom page/tour checks did not execute the entire checked-in
layout chain. Review 147 identified stale selectors, a lost accessible status and
a few missed terms. The same branch corrects these without API/backend/route or
Discord-template changes. Finalize's computed name now includes Unpublished
changes or Published and current while its visual label stays compact. The real
Chrome layout suite checks computed names, not only serialized attributes.

One signup is singular; Declaration differences use Unplaced, and the staff
account picker explicitly names player-or-clan search. Linking help again gives
context for a missing account and different owners. An all-waiting member has
one card containing status, accounts and Refresh; mixed assigned/waiting groups
retain their separate waiting list. Ready means the configured 15/30 CWL count is
full with fresh in-clan observations, per `summarizeArrivalReadiness`; it does not
claim all 50 physical clan slots are occupied.

A source-policy regression covers 20 canonical UI terms plus linking/obsolete-label
checks. All 20 newly defined canonical revert mutants fail assertions and restore
cleanly; these are not described as rerunning the refuter's unavailable original
mutant index. The full frontend has 1,576 passing tests in 269 files; TypeScript and the
production build pass. The complete checked-in `npm run test:layout` command
passes through its final tracking-cadence and shell-Back cases. This includes
all existing main-page fixtures, four computed-name states, 13 unified Members
cases and four retained editor/nickname-review widths. Final narrow/wide Signup
images were visually reviewed: active pool context stays visible and the first
account name remains above the sticky bar. The words-only 119 caption had
unintentionally added vertical space; removing that redundant paragraph fixes
the actual narrow regression without changing CSS, controls or assertions.

Initial complete-command failures (stale version selector, the first-account
regression, duplicate canonical navigation labels, and an asynchronous avatar
focus assertion) remain recorded. Targeted migration failures also remain:
default bots-hidden totals, a region/input selector collision and a malformed
legacy import fixture after its first width. The final full command passes with
no excluded cases. The canonical 13 Members cases are additive, not a substitute
for the retained four profile/nickname flows. Fake signup/profile/role/moderation
writes in the suite are isolated test data; no live delivery is claimed.

Final evidence is `.local/p147-ready-evidence.json`,
`.local/p147-full-layout-host-attempt5.log`, `.local/p147-layout-attempt5/`,
`.local/p147-mutants.json` and `.local/p147-api-proof.json`. The latter compares
41 runtime files to the pre-119 revision and preserves API arguments and existing
link destinations. Existing large-chunk and isolated fixture deprecation/cache
fallback warnings remain. This is frontend-only; no backend full suite or live
production probes were needed. Release remains held.

The complete layout chain also exposed a stale pre-Members fixture. The old
`/server/member-timezones` route already redirects to unified Members, whose
validated directory the old fixture did not supply. The test runner now uses the
existing unified fixture and retains its imported legacy data. Thirteen existing
Members overview/keyboard/bulk cases are additive to four migrated time-zone and
nickname-review cases; they do not replace the older editor coverage.

| Former gate                                      | Retained current gate                                                                                                                                    |
| ------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Old route and 25 compact table rows              | Canonical Members alias, 25 rich records, actions above, current first-row/single-scroll/44 px contract                                                  |
| Source chips Saved/From nickname/Unknown/Missing | Saved GMT-5 precedence, parsed NZT, missing zone/flag; Unknown Cedar remains in Check name review. Removed source chips are not asserted as current UI.  |
| All directory members                            | Default 1,411 nonbots, then explicit Bots filter shows all 1,448 fixture members                                                                         |
| Direct profile editor                            | Person Details → time zone/flag editor; AU/US choices, all 26 zones, linked name, 409 draft preservation, retry, explicit Back and restored row focus    |
| Nickname review                                  | Bots excluded, 25-row pages, Check name/Cedar, hidden selection/reveal, sticky Rename, Clear/two-person confirm, Stop, owner refusal and no raw actor ID |
| Layout and destinations                          | Four widths 320/360/390/1440, minimum text/controls, no overflow/errors, bounded synthetic save/import/preview/confirm/stop writes                       |

The accepted rich records replace the retired 70–90 px table geometry; the
accepted Details panel stays open after profile save until Back is pressed. No
product behavior or permissions were changed to make the legacy test pass.
Fixture-only corrections give imported profiles their required nullable fields,
filter active runs exactly as the existing store does (`state=queued`), and reset
mutable sample data between widths. The fixture's extra last person explains the
one-member difference from its old 1,447/1,410 totals.

A source-only investigation of the one-off browser-issue POST found that the
unchanged `api.ts` catch also reports an intentional AbortError as network_error.
An actual-source VM probe reproduces that path with an in-memory fetch stub and
zero network calls. It is a plausible cancellation cause, not identification of
the refuter's event without its original kind/error. No telemetry/API behavior
is changed in this wording batch.
