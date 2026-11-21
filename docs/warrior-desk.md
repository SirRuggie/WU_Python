# Warrior Desk

Warrior Desk is a second public panel for existing Warriors: **Add another
account** (`account`) and **Contact staff** (`staff`). Apply continues to open
Main/FWA recruit tickets. This is the prompt 261 rebuild of the cached PR #307;
its replacement PR supersedes #307 without closing it.

The November 12 decisions remain, with Ruggie's November 20 decisions 1–9 and
handoff entries 1265–1267. The latter replace the proposed member Reopen button:
**the member's own message reopens a Close ticket during its 60-day window**.
There is no new Reopen button or intake panel. Staff-facing links say **Ticket
thread**; member-facing Desk copy says request. Both account questions remain:
“How many accounts do you want to add?” and “Send the player tag of each account.”
Contact staff has no questionnaire and finishes with **Done**.

## Configuration and posting

Configuration remains in `ticket_setup`, `_id: "config"`. Pure validation and
history projections belong to `utils/ticket_settings.py`; HTTP and Discord
adapters do not import one another for them.

| Key                             | Meaning                                       |
| ------------------------------- | --------------------------------------------- |
| `desk_channel_id`               | Panel and private member-thread parent.       |
| `desk_staff_parent`             | Staff parent; empty uses `main_staff_parent`. |
| `account_thread_recruiter_role` | Add account handler role.                     |
| `staff_thread_recruiter_role`   | Contact staff handler role.                   |

The existing rollout stores `desk_intake` (guild/channel/message). Desk requests
route only through that exact binding, in `thread_default` or `thread_only`.
Other phases reject them. Recruit and legacy routing remain separate. Pilot/test
windows and staff-created tickets remain Main/FWA.

Ticket settings → Warrior Desk shows each missing saved prerequisite, with a
field-focus link where applicable. Unsaved edits disable posting. Post is the
primary action only before the panel is live; **Repair panel** is secondary for
an existing binding. Both use the existing confirmation, revision and worker
receipt path. Posting requires the saved channel, effective staff parent, both
roles and the allowed rollout phase; native validation checks Discord ownership,
permissions and roles again before any post or configuration change.

**Release/setup is guided by Ruggie under entry 1251 after Shaka approval.** No
code path in development changes live settings, channel permissions, bindings or
Discord posts. There is no migration, backfill or automatic conversion of old
public thread pairs.

## Per-type authority

Dashboard access additionally requires dashboard Tickets permission. Every list,
conversation read and ticket action applies the canonical ticket's type gate;
Link account also retains its existing weight permission. Global flag-by-ID
write authority remains recruiter/admin authority rather than a new global
privilege for a Desk role.

| Actor in the configured guild | Main | FWA | Add account | Contact staff |
| ----------------------------- | ---- | --- | ----------- | ------------- |
| Administrator                 | Yes  | Yes | Yes         | Yes           |
| Main recruiter                | Yes  | Yes | Yes         | No            |
| FWA recruiter                 | Yes  | Yes | Yes         | No            |
| Account role                  | No   | No  | Yes         | No            |
| Staff role                    | No   | No  | No          | Yes           |
| None / another guild          | No   | No  | No          | No            |

`perms.is_recruiter` keeps its recruit meaning. `is_ticket_staff` admits console
access; `allowed_ticket_types` and `can_handle` provide the shared per-type scope.
Linked-account review checks the canonical ticket, and onboarding's `open_ticket`
lookup explicitly excludes Desk requests. `/tickets list` uses these helpers and
groups Main, FWA, Add account and Contact staff, oldest first, with a 100-row bound.

## Private thread membership

New Desk-enabled pairs use private staff threads. Main/FWA staff threads invite
both recruiter roles; account staff threads invite the account role plus both
recruiter roles; Contact staff invites only its staff role. Candidate threads
preserve their member and invite the same exact handlers. Administrator access
is inherent in Discord. Extra configured viewer roles may read the parent but
are not invited to every private thread. Sharing a parent never unions unrelated
types' invitation sets.

Discord's **Manage Threads** permission can view all private threads. Guided
readiness therefore rejects non-admin roles/members which can bypass membership
in a new private parent, including combined roles and member overwrites. The bot
retains its required permissions. Every handler role must have parent read,
history and thread-send permission. Existing public pairs keep their previous
behavior; this change does not claim to make their historical access private.

Ticket handler roles may hold Manage Threads in Desk parents; they can read all Desk threads (Ruggie, 2026-11-21).

Creation snapshots retain typed role identities for restart recovery. A bounded
member snapshot is shared across the pair; enumeration failure or more than
10,000 members blocks the attempt rather than publishing an incomplete pair.
Membership preparation has a 120-second bound. Role events reconcile up to 50
marked pairs within 30 seconds; the existing maintenance task pages five pairs
per pass and covers missed events/restarts and configuration changes. Stale
invitations are removed before additions, with fresh role checks before grants.
This is eventual reconciliation, not a promise of instantaneous Discord role
revocation. Archived-thread invitation behavior has not been verified live.

## Close, Done and member reopening

Close is not Approve or Deny. It archives the member thread **unlocked** for 60
days from `closed_at`, preserving reading and membership. Staff-thread close
behavior is retained. Done uses the same Close status and note, whose field label
is **Note for the member (shown in their thread)**. Staff may reopen at any time.

Only the bound member's own non-bot, non-webhook message in the canonical member
thread, after its close and within 60 days, can invoke the existing reopen path.
That path retains slot ownership, revision CAS, deleted-thread checks, pending
Ghosted/effect guards, member audit and the existing staff notification. Mongo's
server clock is part of the atomic member-only deadline predicate; a delayed
slot claim cannot extend the window. Two messages can win only one transition.
If the slot is full, the ticket remains closed and one notice is attempted per
close revision. Its attempt is claimed before sending; an uncertain acceptance
is not automatically replayed.

My Tickets queries only the configured guild and that member. It lists open and
Close-within-60-days tickets with the **same presentation**, no Closed label or
extra closed-state wording. Approved, Denied and expired Close tickets are
excluded. The result is bounded to ten. Opening My Tickets does not unarchive a
closed thread.

The existing archive task also pages 25 expiry candidates, independently of the
quiet-archive setting/daily completion marker, with a durable per-guild claim
allowing at most one page attempt per hour (also across restarts). A proven lock,
already-locked thread or missing thread records `member_window_locked_at` for
that Close generation; completed rows are not fetched again. Close/Reopen clears
completion for a new window. After 60 days it locks the member thread; messages
never reopen an expired ticket. A durable maintenance marker
allows a later pass to repair an interrupted lock even if the ticket reopened
and the post-lock read failed. A concurrent successful reopen wins. These are
scheduled, bounded sweeps rather than an exact-second timer.

Periodic staff-access reconciliation keeps its five-pair page and 30-second
budget. Eligibility and an atomic per-ticket hourly attempt claim precede REST,
so unscanned pairs progress without repeatedly fetching recently checked rows.
A failed REST attempt becomes eligible again after an hour. The cursor wraps
when eligible rows are exhausted. Role-change events bypass this periodic gate
and retain their immediate, bounded first-50-pair path; larger offline backlogs
still require multiple pages.

Official Discord documentation states that sending a message unarchives an
unlocked thread and requires membership plus `SEND_MESSAGES_IN_THREADS`:
[threads](https://github.com/discord/discord-api-docs/blob/main/developers/topics/threads.mdx).
The server-time predicate uses documented MongoDB
[`$expr`](https://www.mongodb.com/docs/manual/reference/operator/query/expr/) and
[`$$NOW`](https://www.mongodb.com/docs/manual/reference/aggregation-variables/).
This is documentary and fixture evidence; no real Discord client test or live
Mongo integration is claimed.

## One-step Ghosted

On an open non-staff ticket, manual Ghosted in Manage Flags or an exact-current-
target `/tickets flag-add` closes the ticket with the same supplied reason.
There is no second modal, Close or note. The shared inactivity Close service
owns the CAS/effects; its durable receipt completes the permanent flag after a
restart or partial failure. The flag storage owner records an idempotent receipt
and preserves a newer staff edit rather than overwriting it. A conflict needs
review; uncertain Discord notifications are not automatically retried.

Terminal tickets are not closed again. Unrelated explicit global identity
arguments never close another ticket implicitly. Contact staff has no Ghosted
set control and refuses stale/direct submissions. Global flag permissions remain
unchanged. Manual open-ticket reasons need 5–500 characters, matching the shared
Close minimum; existing terminal flag-only behavior remains available.

## Ticket Command and dashboard

Ticket Command keeps three oldest-first dropdowns, capped at 25 each. Options
use `Type #n · name` and an absolute UTC opened date; labels perform no per-row
flag/name lookup. Private account details retain Ticket thread / Staff thread,
Link account, Approve and Deny; staff details retain thread links and Done.
Old shared decision IDs only refresh or show a stale-modal notice. They cannot
mutate a ticket. The new Warrior Desk statistics section shows account approved /
open / denied and staff done / open, using the existing status-bar renderer.

All eleven original static ticket assets and `console_render.py` are byte-equal
to base `5edbe19c`; the cached chart-title change was discarded. Dynamic counts
may of course change chart content. No overall pixel-identity claim is made.

Dashboard Tickets has full-width search, the merged list toolbar, only permitted
All / Recruits / Accounts / Staff scopes, and the existing status/flag/date panel.
A single permitted group hides the scope control. Whole rows are real read links
with the specified accessible name, type icon, absolute date and name-line flag.
Validated `ticket=ticket_<id>` URLs support new tabs and Back/Forward using the
existing dashboard history contract; deep reads obtain identity from the
existing authorized messages GET. No new endpoint or transcript storage exists.

`utils/ticket_access.py` is the shared pure configured-guild/admin/type-role
calculation used by Discord and HTTP authorization. `utils/ticket_rollout.py`
owns the rollout read model/parser and public read; the bot runtime reexports
those exact objects and retains the existing writes, indexes, claims and slots.

## Verification status and limits

Implementation is under review. The full frontend recorded 418 files / 2,924
passing tests, TypeScript, Vite and scoped formatting. Its receipt-only tail
initially failed from a missing import; saved asset hashes were recovered without
rerunning those checks. The first full backend recorded 9,546 passed / 12 failed;
a shared-service import-boundary repair and intentional obsolete-contract test
updates then passed 377 focused tests (one skipped, 38 subtests). That failed full
run remains evidence; the final backend outcome and native originals belong in
the review artifact. No deployment, live Discord delivery, physical-phone or full
assistive-technology claim is made. The replacement PR requires Shaka's current-
head review and Ruggie's guided setup; PR #307 remains untouched.
