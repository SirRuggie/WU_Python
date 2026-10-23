# Recruitment Staff Thread

Open `/manage` → **Recruitment → Recruitment Staff Thread**, then choose Main or
FWA. Requires Manage Server or Administrator. Every action verifies the editor
owner, server, expiration, and current permission.

Each section has one modal containing an optional heading and its message body.
Main contains the private-thread notice, how-heard question, and interest hook.
FWA additionally contains the donations/clan-chat message. Preview is private and
suppresses all mentions. Save template applies to newly created tickets only.
Existing staff conversations are not rewritten. Unsaved draft changes expire.

The correct configured Main/FWA recruiter role is automatically prepended to the
private-thread notice. The opening staff card remains the notification; talking
points do not ping staff a second time. These messages never go to the applicant
thread. Isolated tests retain their existing notification suppression.

## Persistence

`utils/ticket_staff_content.py` owns schema version 1. `ticket_staff_templates`
is explicitly declared in `utils/mongo.py` in the configured production database.
It contains permanent configuration only, keyed `<guild_id>:<main|fwa>`, with
integer identities, bounded section text, revision, updater and UTC BSON date.
The natural `_id` index enforces uniqueness; revision CAS rejects stale saves.
No audit arrays, ticket rows or expiring editor sessions share this collection.
The future database naming migration should include this collection unchanged.

Drafts use the shared 30-minute component-state TTL. New tickets snapshot their
saved template before opening-message delivery. Recovery uses that snapshot so
later template edits cannot duplicate or alter a partially delivered sequence.
Tickets created before this feature continue to use the original default text.

## Flew the Coop flag

Recruiters can choose **Flew the Coop** in Manage flags or `/tickets flag-add`.
A reason is required. This durable identity flag appears with its reason on
future staff context cards alongside previous ticket decisions; a new ticket
remains open for recruiter review. It does not automatically approve applicants.

Applying or removing the flag reconciles both applicant and staff thread names,
including closed tickets, preserving archive/lock state through durable recovery.
The additive marker matches `🐔 ✅ main-404-iankellum`: existing status emojis and
custom title text remain. Discord's 100-character name limit still applies, so
adding the marker to a maximum-length title truncates its ending. No data
migration is required. The web ticket browser shows active reasons and supports
flag filtering/name search behind its existing recruiter authorization.

Validation: 356 ticket regression tests and 275 frontend tests passed, as did
the frontend build. Dashboard visual-review scope is recorded in the interaction
standard. Discord thread metadata was read to confirm the naming example; no
live flag writes, test messages, or production deployment were performed.
