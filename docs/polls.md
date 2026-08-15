# Polls

Status: **current repository behavior**, reconciled on **2026-08-14**. This page
does not establish that the feature has been deployed or smoke-tested in current
production.

Polls are server-scoped Components V2 messages. Administrators create and
inspect them; every server member may vote through the buttons on the public
poll message.

## Commands and access

| Surface | Who can use it | Purpose |
|---|---|---|
| `/poll create` | Server administrators | Create a timed poll in the current server channel. |
| `/poll view` | Server administrators | Inspect a poll and its named voter breakdown. |
| `/poll active` | Server administrators | List polls that are currently open in the server. |
| Vote buttons | All server members | Cast or change one vote on an open poll. |
| **View voters** | Server administrators | Open the named voter breakdown from a poll message. |
| **End poll** | Server administrators | Close an open poll immediately. Any administrator may close it, not only its creator. |

The commands are server-only and administrator-only. Component handlers repeat
the relevant guild and administrator checks because the shared dispatcher does
not provide authorization on their behalf.

## Creation contract

A poll has:

- a title or question;
- two required options and one optional third option;
- one duration written as a positive whole number plus `m`, `h`, or `d`, from
  **5 minutes through 7 days**; and
- at most one optional role ping.

The duration option is free text with advisory autocomplete suggestions for
`1h`, `2h`, `4h`, `8h`, `12h`, `1d`, and `2d`; those suggestions are not fixed
choices. Administrators may submit any valid in-range value such as `45m`,
`90m`, `3h`, `6h`, or `7d`. Input is case-insensitive and surrounding whitespace
is ignored. Compound or natural-language values such as `1h30m` and `90 minutes`
are rejected. The duration begins when the approved five-field creation modal is
submitted.

The role selection belongs to that one poll. It does not grant the creator a
general announcement or mention capability.

## Voting and visibility

Voting is button-based. Reaction voting and select-menu voting are not part of
this feature.

Each member has one current vote. Choosing another option replaces the previous
choice instead of adding a second vote. Voting stops once the persisted deadline
passes or an administrator closes the poll.

An active poll uses a gold Components V2 container with the custom
`<:poll_graph:1537995208845824051>` icon beside the question headline and
optional details immediately below it. Every option uses the same two-line
layout: its numbered label appears first, followed by a plain 20-cell `█`/`░`
bar with an integer half-up percentage and compact vote count. Voting buttons
use the same option numbers. The existing `assets/Gold_Footer.png` Media Gallery
treatment separates those controls from the quiet total-vote, closing-time, and
creator footer.

The public poll message shows option totals and percentages but never names the
voters. Named votes are deliberately restricted to administrator-only
`/poll view` and **View voters** responses. The public card does not show its
Poll ID; administrator-only views and lists retain the ID for lookup. This is
visibility control, not an anonymous ballot: Discord user IDs remain stored
with the poll so the bot can enforce one changeable vote and produce the
administrator breakdown.

## Persistence and deadlines

[`utils/poll_store.py`](../utils/poll_store.py) owns durable poll operations over
the `settings.wu_discord_polls` Mongo collection. User-facing reads and writes are
scoped by guild. Vote writes also require the poll to remain active and its
`ends_at` deadline to remain in the future.

WU deliberately does not share Arcane's `settings.discord_polls` collection.
Poll rows contain bot-owned Discord message IDs, so sharing them would make each
application schedule and attempt to edit messages posted by the other bot.

Active polls have no TTL field. Their durable records retain the message
location, options, creator, deadline, status, and user-to-option vote mapping so
a process restart does not reset voting or business time.

Closing a poll is atomic and idempotent. The first successful close records the
end reason and time, marks the poll inactive, and sets `purge_at` to 30 days
after `ended_at`. Mongo's TTL index then removes the completed poll. A repeated
manual or scheduled close does not replace the original end state or restart the
retention window.

Scheduled close jobs are in-memory execution aids, not persistence. At startup
the poll lifecycle restores future deadlines from Mongo and closes active polls
whose deadlines passed while the bot was offline. The rendered public message
is updated to the ended tally when Discord still makes that message available;
the durable Mongo transition remains authoritative.

Public-message rendering has its own durable recovery marker. A transient
Discord edit failure leaves `message_sync_pending` set, schedules a retry, and
is retried again after restart. Deleted or forbidden messages are recorded as
terminally unavailable instead of retrying forever. Deadline restoration runs
before index installation, so an index/TTL permission problem can delay history
cleanup but cannot prevent otherwise-valid polls from closing.

## Source boundaries

- [`extensions/commands/poll.py`](../extensions/commands/poll.py) owns
  slash-command registration, Components V2 rendering, component authorization,
  and scheduled message updates.
- [`utils/poll_store.py`](../utils/poll_store.py) owns guild-scoped reads, atomic
  vote/end transitions, indexes, and retention fields.
- [`extensions/components.py`](../extensions/components.py) routes the custom
  buttons and modal submission. Its action names and custom-ID shape are posted
  message compatibility contracts.
- [`utils/mongo.py`](../utils/mongo.py) exposes the WU-only
  `wu_discord_polls` collection through the `discord_polls` attribute.

Current code and focused tests are authoritative if this dated page drifts from
the implementation. Repository behavior alone is not deployment evidence.
