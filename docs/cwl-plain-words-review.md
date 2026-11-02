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
  match. Native month-edit inputs and request/CSV/Discord values stay raw; only
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
