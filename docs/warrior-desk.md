# Warrior Desk

A second public panel for existing Warriors. Two buttons open a private thread
per request: **Add another account** (`account`) and **Contact staff** (`staff`).
The recruit panel (Apply, `main` and `fwa`) is unchanged.

Owner decisions: `D1`-`D7` of the Warrior Desk task (2026-11-12). Wording rule:
user-facing text says "request", never "ticket" or "support".

## Types and config

`schema.DESK_TICKET_TYPES = {account, staff}`; `schema.RECRUIT_TICKET_TYPES =
{main, fwa}`; `TICKET_TYPES` is the union. Config keys live in `ticket_setup`
`_id: "config"`:

| Key | Meaning |
|---|---|
| `desk_channel_id` | Panel channel. Member threads are private threads here. |
| `desk_staff_parent` | Staff thread parent. Empty falls back to `main_staff_parent`. |
| `account_thread_recruiter_role` | Role that handles `account` requests. |
| `staff_thread_recruiter_role` | Role that handles `staff` requests. |

`thread_service.parents_from_config` maps both desk types to these keys and
raises `ThreadConfigurationError` for an unknown type. The staff-thread role set
includes every type whose staff parent is the same channel.

## Routing

The rollout document gets an optional `desk_intake` (guild, channel, message).
Absent means the desk panel is inactive. `route_public_intake` sends desk types
only to `desk_intake`, and only in `thread_default` / `thread_only`; every other
phase rejects. `main` / `fwa` routing is unchanged. `configure_rollout` with
`desk_intake=None` keeps any stored binding. The desk channel is not part of the
"candidate parent equals the Apply channel" checks.

## Permissions

- `perms.is_recruiter` is unchanged: the Main or FWA recruiter role, or
  Administrator. Staff-create, flag writes by ID and every recruit action keep it.
- `perms.is_ticket_staff`: `is_recruiter` or the account/staff role. It is used
  only for console access (Ticket Command, Find, Browse, Member History) and as the
  first gate before `can_handle`.
- `perms.can_handle(member, mongo, ticket_type)`: for `main` and `fwa`,
  `is_recruiter` (either recruit role, as before); for `account` and `staff`,
  Administrator or that type's role.
- Every state change checks `can_handle` with the ticket's own type: approve,
  deny, overturn (`resolve`), close / Done / reopen (`lifecycle`), console detail
  views and confirm panels, flag manager (`console._latest_flag_ticket`),
  slash `/deny`, `/flag` from a ticket thread, player info, inactivity decisions.

## End states

- `account`: recruit pipeline (linked-account checks, flags, blacklist,
  Approve / Deny). Only a written reason denies; the default FWA / Main bodies
  are hidden and rejected. Approval card: "Staff approved your new account."
  Staff card: `ACCOUNT #n - Approved/Denied`.
- `staff`: no Approve / Deny. **Done** is the existing `closed` status with a
  note of 5-1000 characters; the thread is archived and locked, Reopen works.
  Member card: "Staff marked this request as done."
- Ghosted prompt and auto-close skip `staff`.

## Copy

- Panel: `## 🛡 Warrior Desk` / "Already a Warrior? Select a button." /
  "**Add another account:** add a Clash account to the family." /
  "**Contact staff:** conflicts, strike appeals and other questions." Buttons
  `ticket_v2_create:public:account` and `ticket_v2_create:public:staff`.
  Content document key `warrior_desk`.
- Account welcome: "## ➕ Add another account" / "Answer here. Staff check your
  accounts." Questionnaire (`thread_service.ACCOUNT_QUESTIONS`, one line each):
  "How many accounts do you want to add?" and "Send the player tag of each
  account."
- Staff welcome: "## 💬 Contact staff" / "Tell us what you need. Staff reply
  here." No questionnaire. No staff talking points for either desk type.
- Staff opening card: "<@&role> a member opened a request."

## Posting the panel

Dashboard Ticket settings has a **Warrior Desk** part (the four keys) and the
tool action `restore_desk_entry` ("Post Warrior Desk panel"), which runs
`settings.repair_desk_entry`: edit the bound message, or post a new one in
`desk_channel_id` and CAS-bind `desk_intake`.

## Console (Ticket Command)

The staff console's open-ticket message has three dropdowns: New recruits
(main + fwa), Add account and Staff, oldest first, 25 per dropdown (more via
Find / Browse). Selecting a ticket opens its private details, gated by
`perms.can_handle` for the ticket's type. Opening or closing an account or
staff ticket refreshes the console the same way as main/fwa
(`thread_service.notify_console_after_change` is type-agnostic). Layout:
[ticket-console.md](ticket-console.md) sections 1 and 2.

## Limits

- Pilot and test windows, staff-created tickets and legacy tickets stay
  `main` / `fwa`.
- Desk-reachable member messages in `handle_create_ticket` say "request";
  only the unknown-type fallback still says "ticket".
- A Ticket Command dropdown keeps one custom id, so Discord may keep the last
  choice shown; selecting the same ticket again may need Refresh first (not
  verified in a live client).
