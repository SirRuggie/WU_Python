# Privacy Policy — WU Wizard

**Effective date:** 2026-09-08

This policy explains what WU Wizard, a Discord bot for the Warriors United
Clash of Clans community, collects, why, and how it is handled.

## Who we are

WU Wizard is run by the operator of WU Wizard (the Warriors United
community, referred to as "we" or "us"). Warriors United is a Farm War
Alliance (FWA) family of Clash of Clans clans. The bot runs on our own
server, with its data stored in MongoDB and its images stored in Cloudflare
R2 (and, for older uploads, Cloudinary).

## What we collect

**Identity.** Your Discord user ID, plus a snapshot of your username at the
time of a ticket or other recorded action.

**Game accounts.** Clash of Clans player tags and in-game names that you
link or enter yourself, and, separately, clan-membership tracking: which
clans a linked player tag has been in, kept with time anchors that expire
automatically.

**Tickets and staff records.** If you open a recruitment ticket, we keep the
answers you give in the ticket flow, the ticket number, timestamps, and the
staff decision (approved or denied, by whom, and the type of denial).
Ticket history is kept permanently as an audit trail. Separately, staff may
keep notes, flags, strikes, and bans about members for recruiting and
moderation purposes; these are visible to staff only, never to other
members.

**Game features.** If you use the Card Collector game, we keep your card
inventory per player tag and a record of trades, including the Discord IDs
of both parties to a trade. We also keep CWL and FWA roster snapshots
(player tags and Discord IDs) to run reminders and pings.

**Uploads.** Clan leaders can upload clan logos, banners, and base layout
images through the bot's upload commands. These are clan assets, not
personal photos, and are stored the same way as any other bot-managed
image.

**Short-lived state.** To make buttons, menus, and multi-step flows work,
the bot temporarily stores component interaction state (kept 24 hours),
todo-dashboard sessions (30 days), ticket-creation leases (up to 30 days),
and challenge messages, reminders, and polls. All of these are deleted
automatically by database expiry; none are kept beyond their stated window.

**Message content.** The bot reads message text only to react to certain
triggers, such as recognizing when someone needs onboarding help — it does
not store message text. The only free text we keep is what you submit
yourself through the bot's own commands and ticket forms.

## Why we collect it

To run recruitment and ticketing, manage clan membership and roles, send
CWL/FWA/raid reminders, operate the Card Collector game, and support
moderation and staff decision-making within Warriors United.

## Where it comes from

- Directly from you, through commands, buttons, and ticket forms.
- From Discord, as part of normal bot operation (your user ID, username,
  and server membership).
- From the Clash of Clans API and from ClashKing, when you link a player
  tag or when the bot looks up war, CWL, or profile data.

## Who we share it with

- **Clash of Clans API**, reached through the ClashKing proxy, and
  **ClashKing's own API**: player tags and clan tags are sent to fetch
  profiles, war, and CWL data. ClashKing's Discord-links service receives
  your Discord user ID paired with your player tag, to look up or record
  linked accounts.
- **FWA points site** (points.fwafarm.com): clan tags only, to read war
  verdicts. No member-level data is sent.
- **BAND** (openapi.band.us and its iCal feeds): the bot only reads the FWA
  sync group's posts and calendar. No member data is sent to BAND.
- **Discord**, under Discord's own Terms of Service and Privacy Policy, as
  the platform the bot runs on.
- **Hosting providers**: MongoDB for stored data, and Cloudflare R2 (with
  legacy images still on Cloudinary) for images.

We do not sell your data, and the bot carries no advertising.

**Internal logging.** A private staff-only log channel in Discord records
certain bot actions, such as messages sent with the announce command and
FWA points results, and a server-side operational journal records similar
events. These logs are for running the server, not for anything beyond it.

## Retention

Ticket records and staff moderation records (notes, flags, strikes, bans)
are kept permanently as part of the server's audit trail and may be
retained even after a removal request, where needed for server safety.
Short-lived items listed above expire automatically on the schedules given.
Everything else is kept until you ask staff to remove it.

## Your choices

There is no self-service delete command. You can ask Warriors United staff
to remove your linked accounts and other personal records, or to unlink a
Clash account from your Discord. Ticket audit records and staff moderation
records may be kept where needed for server safety even after such a
request.

## Security

Access to stored data is limited to bot operators and Warriors United
staff. Credentials and other secrets are kept out of the bot's source code.

## Children

Discord requires all users to meet its own minimum age. We do not knowingly
collect data from anyone below that age. If we learn that we have, we will
delete it on request.

## Not affiliated with Supercell or Discord

This material is unofficial and is not endorsed by Supercell. For more
information see Supercell's Fan Content Policy:
www.supercell.com/fan-content-policy

WU Wizard is not made, endorsed, or supported by Discord Inc. Discord's own
handling of your data is governed by Discord's Privacy Policy, separate
from this document.

## Changes to this policy

We may update this policy as the bot's features change. The version posted
at this URL is the current one.

## Contact

Questions about this policy, and requests to remove or unlink your data, go
to Warriors United Discord server staff. Open a ticket or message a staff
member on the Warriors United Discord server.
