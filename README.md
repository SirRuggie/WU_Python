<div align="center">

# WU Bot

**The Discord bot that runs the Warriors United Clash of Clans family.**

Recruiting and onboarding, FWA and CWL coordination, a full ticket desk, and a
per-player to-do dashboard — 79 documented slash commands and six always-on
background jobs behind a single bot account.

[![Python 3.12.3+](https://img.shields.io/badge/Python-3.12.3%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![hikari](https://img.shields.io/badge/hikari-2.6.0-5865F2)](https://github.com/hikari-py/hikari)
[![hikari-lightbulb](https://img.shields.io/badge/lightbulb-3.2.6-FFD43B)](https://github.com/tandemdude/hikari-lightbulb)
[![coc.py](https://img.shields.io/badge/coc.py-3.10.0-E8590C)](https://github.com/mathsman5133/coc.py)
[![MongoDB](https://img.shields.io/badge/MongoDB-async-47A248?logo=mongodb&logoColor=white)](https://www.mongodb.com/)
[![Tests](https://img.shields.io/badge/tests-pytest-0A9EDC?logo=pytest&logoColor=white)](tests/)

</div>

<img src="assets/Purple_Footer.png" width="100%" alt="" />

**Legal:** [Terms of Service](docs/terms-of-service.md) · [Privacy Policy](docs/privacy-policy.md)

## Contents

- [What it does](#what-it-does)
- [Background jobs](#background-jobs)
- [How it's built](#how-its-built)
- [Repository layout](#repository-layout)
- [Getting started](#getting-started)
- [Testing](#testing)
- [Documentation](#documentation)
- [Deployment](#deployment)
- [Working on this repo](#working-on-this-repo)
- [Credits & disclaimer](#credits--disclaimer)

## What it does

WU Bot is the operational backbone of the Warriors United Discord server: members
manage their own Clash accounts and obligations, recruiters run onboarding end to
end, and leadership coordinates FWA wars, CWL, and clan administration — all
through slash commands rendered with Discord's Components V2 UI (containers,
sections, and media galleries rather than classic embeds).

Every public command lives in the in-app guide (`/help`) and is inventoried in
[`extensions/commands/help_catalog.py`](extensions/commands/help_catalog.py),
which is updated in the same change as any command it describes. The tables
below are drawn from that catalog.

### 🧭 Player self-service

Members help themselves without pinging leadership: `/accounts` shows every
Clash account linked to their Discord, `/todo` shows what those accounts still
owe — war attacks, CWL, raid weekend, and more — and `/family-links` manages
family roles and open clan links.

<details>
<summary><strong>Command reference — Start Here (5 commands)</strong></summary>
<br>

| Command | Description |
| --- | --- |
| `/help` | Open this command guide. |
| `/accounts` | Show every Clash account linked to your Discord. |
| `/todo` | Show what your linked Clash accounts still need to do. |
| `/family-links` | Manage your own family roles and open clan links. |
| `/slap` | Send a playful slap GIF to another member. |

Right-click a user → **Apps → Get User ID**, or a message → **Apps → Get
Message ID**, to copy Discord IDs directly.

</details>

### 👥 Recruiting & onboarding

Recruiters get a complete pipeline: a questionnaire for new recruits, a
full onboarding dashboard with a guided server walkthrough, one-off and bulk
role management, and standing setup posts covering the family overview, war
rules, and the strike system. A background task removes the temporary New
Recruit role automatically two hours after assignment.

<details>
<summary><strong>Command reference — Roles &amp; Recruits (8 commands)</strong></summary>
<br>

| Command | Description |
| --- | --- |
| `/role add` | Add one server role to a member. Recruiter/Admin only. |
| `/role remove` | Remove one server role from a member. Recruiter/Admin only. |
| `/role manage` | Open bulk role management for a member. Recruiter/Admin only. |
| `/recruit questions` | Send the recruitment questionnaire to a recruit. |
| `/recruit dashboard` | Open the complete new-member onboarding dashboard. |
| `/setup recruit-aboutus` | Post the family overview and onboarding flow. |
| `/setup recruit-familyparticulars` | Post family particulars and war rules. |
| `/setup recruit-strikesystem` | Post the strike-system rules. |

</details>

### ⚔️ Clans & FWA

Clan administration and the family's FWA toolkit: clan dashboards and info
hubs, logo and banner uploads, FWA base layouts, FWA Chocolate lookups, war
weight calculation, Town Hall upgrade notes, and one-command war plans for
win, loss, blacklist, and mismatch scenarios. The LazyCWL suite snapshots FWA
rosters during CWL, pings players who still need to return for sync wars, and
can run those pings automatically on a schedule.

<details>
<summary><strong>Command reference — Clans &amp; FWA (21 commands)</strong></summary>
<br>

| Command | Description |
| --- | --- |
| `/clan dashboard` | Open clan administration and FWA data tools. |
| `/clan info` | View information about every family clan. |
| `/clan list` | Pick a clan to view or assign to a recruit. |
| `/clan upload-images` | Upload a clan logo and banner. |
| `/fwa bases` | Select and display an FWA base layout. |
| `/fwa blacklist list` | Show every clan on the FWA blacklist. |
| `/fwa blacklist add` | Add a clan to the FWA blacklist. |
| `/fwa blacklist remove` | Remove a clan from the FWA blacklist. |
| `/fwa chocolate` | Look up a player or clan on FWA Chocolate. |
| `/fwa links` | Open FWA verification and war-weight links. |
| `/fwa new-th-upgrade` | Display FWA Town Hall upgrade notes. |
| `/fwa points` | Show the latest stored FWA points verdicts. |
| `/fwa upload-images` | Upload FWA war and active base images. |
| `/fwa war-plans` | Generate a war plan for win, loss, blacklist, or mismatch. |
| `/fwa weight` | Calculate war weight from a storage value. |
| `/fwa lazycwl-snapshot` | Snapshot FWA rosters for LazyCWL tracking. |
| `/fwa lazycwl-ping` | Ping missing players to return for FWA sync. |
| `/fwa lazycwl-status` | List active LazyCWL snapshots. |
| `/fwa lazycwl-roster` | View a LazyCWL snapshot roster. |
| `/fwa lazycwl-reset` | Deactivate completed LazyCWL snapshots. |
| `/fwa lazycwl-autopings-start` | Start periodic missing-player pings. |
| `/fwa lazycwl-autopings-stop` | Stop periodic pings for a snapshot. |
| `/fwa lazycwl-autopings-status` | Show active auto-ping schedules. |
| `/fwa lazycwl-remove-player` | Remove players from snapshot tracking. |

</details>

### 🎫 Tickets

A recruitment ticket desk with separate Main and FWA counters: an entry panel
for applicants, claim/release/approve/deny for recruiters, a management
dashboard, and a channel monitor that keeps ticket records honest. Maintenance
commands diagnose drift between Discord channels and stored records, close
ghost tickets, repair mismatches, and migrate legacy data.

<details>
<summary><strong>Command reference — Tickets (14 commands)</strong></summary>
<br>

| Command | Description |
| --- | --- |
| `/ticket claim` | Claim the current ticket. Recruiter only. |
| `/ticket release` | Release your claim on the current ticket. |
| `/ticket approve` | Approve the current ticket. Recruiter/Admin only. |
| `/ticket deny` | Deny the current ticket. Recruiter/Admin only. |
| `/ticket list` | List all currently open tickets. Recruiter only. |
| `/ticket dashboard` | Open the ticket management dashboard. Recruiter only. |
| `/ticket setup` | Post the ticket entry panel. Admin only. |
| `/ticket config` | Configure ticket roles and categories. Admin only. |
| `/ticket change-category` | Change the category used for new tickets. Admin only. |
| `/ticket reset-counter` | Reset Main/FWA ticket counters. Admin only. |
| `/ticket diagnostics` | Compare ticket channels and stored records. Admin only. |
| `/ticket cleanup-ghosts` | Close records whose Discord channel is gone. Admin only. |
| `/ticket fix-mismatched` | Repair status/channel-name mismatches. Admin only. |
| `/ticket migrate-store` | Copy legacy ticket rows to the tickets collection. Admin only. |

</details>

### 📅 CWL & reminders

CWL logistics on autopilot: announcement posts, LazyCWL preparation notices, a
bonus-medal lottery with named recipients, and a monthly reminder schedule with
configurable follow-ups that survives bot restarts.

<details>
<summary><strong>Command reference — CWL &amp; Reminders (12 commands)</strong></summary>
<br>

| Command | Description |
| --- | --- |
| `/cwl-announcement` | Post a CWL announcement. |
| `/lazycwl-bonuses` | Randomly select LazyCWL bonus recipients. |
| `/lazyprep` | Post LazyCWL preparation announcements. |
| `/cwl-reminder schedule` | Schedule the monthly CWL reminder. |
| `/cwl-reminder status` | Show the active reminder schedule. |
| `/cwl-reminder cancel` | Cancel the scheduled reminder. |
| `/cwl-reminder test` | Send a test reminder. |
| `/cwl-reminder add-followup` | Add or update a follow-up reminder. |
| `/cwl-reminder remove-followup` | Remove a follow-up reminder. |
| `/cwl-reminder list` | List every configured reminder. |
| `/cwl-reminder test-all` | Test all reminders in sequence. Admin only. |
| `/cwl-reminder send-now` | Send all reminders immediately. Admin only. |

</details>

### 🛠️ Operations

Admin tooling for running the bot itself: timed polls with named votes, sending
messages as the bot, emoji management, an owner-only `/reboot` that DMs you when
the bot is back online, and full Discord-side configuration of the BAND sync
alert and FWA points monitors — no shell access required.

<details>
<summary><strong>Command reference — Admin Tools (19 commands)</strong></summary>
<br>

| Command | Description |
| --- | --- |
| `/poll create` | Create a timed poll with named votes. Admin only. |
| `/poll view` | View recent polls or named voters for one poll. Admin only. |
| `/poll active` | List polls that are currently open. Admin only. |
| `/say` | Send a message as the bot. Restricted role only. |
| `/steal` | Copy an emoji into the bot application. |
| `/reboot` | Restart the bot process. Owner only. |
| `/toggle-debug` | Toggle verbose BAND monitor logging. Admin only. |
| `/fwasync enable` | Enable BAND iCal sync alerts. Admin only. |
| `/fwasync disable` | Disable BAND iCal sync alerts. Admin only. |
| `/fwasync status` | Show BAND sync configuration and state. Admin only. |
| `/fwasync check` | Fetch feeds and report upcoming syncs without DMs. Admin only. |
| `/fwasync preview` | Preview the next sync alert in your DMs. Admin only. |
| `/fwasync set-recipients` | Replace sync-alert recipients. Admin only. |
| `/fwasync set-offsets` | Replace sync-alert timing offsets. Admin only. |
| `/fwapoints enable` | Enable the FWA points monitor. Admin only. |
| `/fwapoints disable` | Disable the FWA points monitor. Admin only. |
| `/fwapoints watch-add` | Add a clan to the points watch list. Admin only. |
| `/fwapoints watch-remove` | Remove a clan from the watch list. Admin only. |
| `/fwapoints status` | Show points-monitor status and records. Admin only. |

</details>

## Background jobs

Six always-on tasks in [`extensions/tasks/`](extensions/tasks) do the work
nobody should have to remember:

| Job | Module | What it does |
| --- | --- | --- |
| BAND post monitor | `band_monitor.py` | Polls the FWA sync BAND group every 10 minutes over the BAND Open API and announces war-sync posts in Discord. |
| BAND sync alerts | `band_sync_ical.py` | Watches the BAND iCal calendar feeds and DMs configured members when a sync is scheduled, approaching, or rescheduled. Ships disabled; turn on with `/fwasync enable`. |
| Clan history tracker | `clan_history_tracker.py` | Discovers cross-clan `/todo` obligations off the interaction path: roster departures, linked-account watches, and live war/CWL rosters. |
| CWL reminder scheduler | `cwl_reminder.py` | Runs the monthly CWL reminder chain and its follow-ups, restoring pending reminders from MongoDB after a restart. |
| FWA points monitor | `fwa_points_monitor.py` | Records FWA points verdicts for watched clans. Ships disabled — the upstream site blocks datacenter IPs — so `/fwa points` degrades gracefully to a link. |
| Recruit role cleanup | `recruit_role_cleanup.py` | Removes the New Recruit role two hours after assignment, sweeping in rate-limit-friendly batches every 30 minutes. |

## How it's built

| Layer | Choice | Notes |
| --- | --- | --- |
| Discord gateway | [hikari](https://github.com/hikari-py/hikari) 2.6.0 | Pinned deliberately — hikari and lightbulb are upgraded only as a coupled pair. See [`docs/hikari-lightbulb-versions.md`](docs/hikari-lightbulb-versions.md). |
| Command framework | [hikari-lightbulb](https://github.com/tandemdude/hikari-lightbulb) 3.2.6 | Slash commands, dependency injection, and extension loading. |
| Clash of Clans API | [coc.py](https://github.com/mathsman5133/coc.py) 3.10.0 | Routed through a hosted API proxy, so no Clash developer key is needed. The pin rationale is documented line by line in [`requirements.txt`](requirements.txt). |
| Database | MongoDB via pymongo `AsyncMongoClient` | Native async driver (not motor), remote deployment. Collection handles live in [`utils/mongo.py`](utils/mongo.py). |
| Scheduling | APScheduler + stored timestamps | Schedules and deadlines are persisted in MongoDB and re-seeded by a startup reconciler rather than held in memory. |
| Media | Cloudflare R2 + Pillow | Uploaded clan logos, banners, and base images, served size-capped through Cloudflare image transformations. Static art ships under [`assets/`](assets), mirroring the bucket layout. Why and how: [`docs/media-hosting.md`](docs/media-hosting.md). |
| UI | Discord Components V2 | Containers, sections, separators, and media galleries throughout. See [`docs/components-v2-in-hikari.md`](docs/components-v2-in-hikari.md). |

Design decisions worth knowing before reading the code:

- **One entry point.** [`main.py`](main.py) builds the gateway bot, wires
  MongoDB, the R2 media store, and the Clash client into lightbulb's DI registry, then
  loads an explicit extension list plus everything
  [`utils/startup.py`](utils/startup.py) discovers. Discovery is AST-based: a
  module is only treated as an extension if it actually binds a lightbulb
  `loader`, so renderers and helpers are never imported by accident.
- **One component dispatcher.** Every button, select menu, and modal routes
  through [`extensions/components.py`](extensions/components.py) with a shared
  error boundary. How routing works — and its known sharp edges — is written up
  in [`docs/component-dispatcher.md`](docs/component-dispatcher.md).
- **Restart safety as a rule.** Deadlines are stored timestamps compared to
  *now*, never in-memory timers. The bot can be down for two days and settle
  everything overdue on its first pass.
- **Load-bearing comments.** [`requirements.txt`](requirements.txt) documents
  why each pin exists and what must move together; [`main.py`](main.py) refuses
  to start on anything older than Python 3.12.3.

## Repository layout

```text
WU_Python/
├── main.py                  # Entry point: gateway bot, DI wiring, lifecycle hooks
├── extensions/
│   ├── commands/            # Slash commands, one module or package per feature
│   │   └── help_catalog.py  #   the tested inventory of every public command path
│   ├── components.py        # Central dispatcher for every button, select, and modal
│   ├── autocomplete.py      # Preloaded autocomplete caches
│   ├── context_menus/       # Right-click apps: Get User ID, Get Message ID
│   ├── events/              # Channel and message event handlers
│   └── tasks/               # The always-on background jobs
├── utils/                   # Shared services: Mongo, Clash client, parsers, emoji, …
├── tests/                   # 42 pytest modules (~960 tests)
├── tools/                   # Read-only diagnosis scripts for live data
├── docs/                    # Project knowledge base — start at docs/README.md
└── assets/                  # Message accent art
```

## Getting started

> [!NOTE]
> WU Bot is purpose-built for a single Discord server. Channel, role, and guild
> IDs for Warriors United live in configuration and source, so running it
> elsewhere means adjusting those values — but everything below applies to a
> development setup too.

**Prerequisites**

- Python **3.12.3 or newer** (enforced at startup)
- A MongoDB deployment and its connection string
- A Discord application with the **Server Members** and **Message Content**
  privileged intents enabled
- A [Cloudflare R2](https://developers.cloudflare.com/r2/) bucket with public
  access for image-upload features (setup in [`docs/deployment.md`](docs/deployment.md))

**Install**

```bash
git clone https://github.com/SirRuggie/WU_Python.git
cd WU_Python
python -m venv venv
venv/bin/pip install -r requirements.txt
```

**Configure**

Create a `.env` file in the repository root (loaded by `python-dotenv`):

| Variable | Required | Purpose |
| --- | --- | --- |
| `DISCORD_TOKEN` | Yes | Discord bot token. |
| `MONGODB_URI` | Yes | MongoDB connection string. |
| `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL` | For image uploads | Cloudflare R2 bucket credentials and its public URL. |
| `R2_IMAGE_TRANSFORMS` | No | `true` once Cloudflare image transformations are enabled on the zone serving `R2_PUBLIC_BASE_URL`; images are then delivered size-capped. |
| `BAND_ICAL_SYNC1` … `BAND_ICAL_SYNC3` | For sync alerts | BAND iCal feed URLs. **Treat these as credentials** — see [`docs/band-ical-feeds.md`](docs/band-ical-feeds.md). |
| `SYNC_DM_USER_IDS`, `SYNC_DM_OFFSETS`, `SYNC_DM_ANNOUNCE_ON_DISCOVERY`, `SYNC_DM_SUMMARY_FILTER` | For sync alerts | Recipients and timing for sync-alert DMs. |
| `BAND_DEBUG` | No | Verbose BAND monitor logging (`true`/`false`). |

**Run**

```bash
venv/bin/python main.py
```

## Testing

The suite is pure pytest, covering the component dispatcher lifecycle,
schedulers, feed and points parsers, the ticket lifecycle, and more.
`conftest.py` puts the
repository root on `sys.path`, so it runs from any working directory:

```bash
venv/bin/pip install -r requirements.txt -r requirements-dev.txt
venv/bin/pytest
```

## Documentation

[`docs/`](docs) is the project's knowledge base — one file per subject, written
because it is fundamental, non-obvious, by-design, or was discovered the hard
way. Start at the [index](docs/README.md). Highlights:

- [`editing-this-repo.md`](docs/editing-this-repo.md) — **read before any bulk
  edit.** In-place `sed`/`awk`/`perl` editing is banned here, with the incident
  history to justify it.
- [`todo-dashboard.md`](docs/todo-dashboard.md) — the `/todo` feature as built,
  including a coc.py enum trap that applies to every Clash state comparison in
  the repo.
- [`hikari-logging-and-warnings.md`](docs/hikari-logging-and-warnings.md) — why
  `GatewayBot.__init__` silently owns `logging` and warning filters.
- [`deployment.md`](docs/deployment.md) — the production host, systemd unit,
  and operator runbook.

## Deployment

Production runs on a Linux VPS under systemd as `wu-bot.service`, with
`Restart=always` (which `/reboot` relies on to come back up) and configuration
supplied by `.env` rather than the unit file. Deploys are performed manually by
the operator: pull, reinstall requirements into the venv, restart the service.
The full topology, runbook, and host baseline live in
[`docs/deployment.md`](docs/deployment.md).

## Working on this repo

A few standing rules keep the codebase healthy:

- **No in-place stream editing.** `sed -i`, `awk`, and `perl -pi` are banned —
  use a real editor or scripted file rewrite, then run the verification greps in
  [`docs/editing-this-repo.md`](docs/editing-this-repo.md).
- **Pins move together.** hikari + lightbulb upgrade as one pair, and the
  coc.py pin has a documented rationale — read the comments in
  [`requirements.txt`](requirements.txt) before touching versions.
- **The help catalog is part of the change.** Adding, renaming, or removing a
  public command updates
  [`extensions/commands/help_catalog.py`](extensions/commands/help_catalog.py)
  in the same commit.
- **Durable knowledge goes to `docs/`.** One file per subject; the index in
  [`docs/README.md`](docs/README.md) links every entry.
- **Run the tests.** `pytest` before handing anything off.

## Credits & disclaimer

- **[FWA](https://www.fwafarm.com/)** and **FWA Chocolate** — the war
  communities and tools this bot coordinates with.
- Built with **hikari**, **hikari-lightbulb**, and **coc.py**.

> This material is unofficial and is not endorsed by Supercell. For more
> information see [Supercell's Fan Content Policy](https://supercell.com/en/fan-content-policy/).

<img src="assets/Purple_Footer.png" width="100%" alt="" />

<div align="center">
<sub>Built and operated for the Warriors United family.</sub>
</div>
