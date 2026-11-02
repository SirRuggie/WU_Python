# Unified Members page: development review

This change replaces the separate Members hub/time-zone directory with one
searchable, selectable list and a reusable person panel. Legacy member deep links
are retained. Per Claude298, the whole page keeps the existing `member_roles`
grant; no new permission or grant migration is introduced. Tickets move to their
own menu group. Protected moderation files and ChannelCombobox are unchanged.

The existing ProfileRuns owner stores typed role manifests and one-at-a-time
children in the existing management lane. Roles do not create a second storage
owner or replay uncertain effects. The separate old time-zone renderer and its
unused styles are removed; its tests now exercise the unified page.

## Review evidence and limits

| Area | Behavior checked |
| --- | --- |
| Access | Actual dashboard policy denies viewers without member_roles before reading a confirmation body; UI makes no directory/run call without access. Profiles-only is not a new grant. |
| Selection | Stable ID sets across search/filter/page, page-only selection, bot exclusion, hidden counts, frozen exact payloads, separate row opener and checkbox. |
| Role changes | Explicit bulk confirmation; one ordinary person applies directly with guarded Undo; protected roles require confirmation; fresh actor/target/bot/roles/guild and policy inputs before a detached fake Discord write. |
| Recovery | Owned Mongo: restart retains done/uncertain/running children, Stop prevents later people, protected confirmation and duplicate confirmation share one durable run/lane. |
| Failure | Unknown confirmation is not automatically retried; unreadable progress blocks new writes until safe refresh; malformed directory/Undo data fails closed; role receipt/audit failures never claim delivery certainty. |
| Editor/navigation | Existing conflict/draft reload, save retry identities, uncertain outcome and country-zone editor cases migrated intact; dirty person changes use the shared discard guard and stable Details history. |
| Layout/keyboard | Four widths320/360/390/1440; usable bounded list, no page overflow, left alignment, hidden-label containment; exact hidden-inclusive bulk/Stop flow. Real Tab/Space/Enter/Escape at360/1440 and640×460, uncovered focus and preserved selection/filter/Back. |

Current checks:1429 full frontend tests in255files;72 focused member/editor/run
cases plus subsequent immediate-role/Undo and dirty-navigation checks;44 focused
backend role/policy cases;4 owned-Mongo role cases. TypeScript and development
builds pass. Additional full backend, required war-reminder, final integration,
requested mutation gates and final screenshot review remain before READY.
Evidence is in `.local/p93-*`. All browser and transport data is disconnected
sample data; Mongo fixtures are owned loopback databases and are removed after
checks. No real roles, nicknames, notifications, imports or DM clicks were tested.


## Final workflow review checkpoint

The whole page keeps `member_roles` under Claude entry 298. Shared editors keep
their existing text and behavior; new page-owned words are in `members/strings`.
Moderation is a generic history link under entry 309; no moderation file changes.

The end-to-end review found and fixed two UI gaps: hidden selected nickname rows
can now be revealed without changing selection or parent filters; a person's
pending or failed role update now stays visible inside the phone/desktop person
panel instead of relying on progress behind that panel. Regressions exercise
the actual components with fake responses.

No old-worker compatibility is claimed for new typed role manifests. Release
requires no queued Standardize or bulk work and the normal 210-second drain. A
rollback after role use must retain a compatible worker or safely freeze queued
role work before an older worker is reintroduced; never erase accepted receipts
or restore production data to make a code rollback appear clean.

Current main includes participation follow-up PR151. Final full backend/frontend,
mutation, keyboard and four-width sample-layout gates remain pending before
READY. No production role or nickname action was performed.
