# Thread-based ticketing + console dashboard — research & proposal

Research deliverable, 2026-08-02. Seven parallel research workstreams, findings
adjudicated against primary sources. It predates the shipped parallel runtime
and is retained for design reasoning, not operator procedure. Use the
[ticket console operations guide](ticket-console-operations.md) for current
commands, authority boundaries, rollout, rollback, drain, and migration.

**Part 2 (dashboard design) is superseded as of 2026-08-17 by
[ticket-console.md](ticket-console.md)** — the decided design, worked out
against an interactive mockup and re-checked against the live codebase. It
caught two mistakes — **both introduced by the mockup, not by Part 2**: a
"Find a ticket" modal carrying select menus alongside its text field (not
buildable on this hikari version — §1.5 already established why, and §2.4
had it right, specifying "single text input (all hikari permits)"), and an
FWA-ban panel rendering a parsed verdict when the real command is a link-out.
Part 2 below is kept for the budget-math and component-cost reasoning, which
is still correct; treat [ticket-console.md](ticket-console.md) as the source
of truth for what shipped.

Part 1 remains useful research. Part 3's one-collection cutover,
`ticket_mode` flag, dual-write plan, and numbered build phases are superseded
by the implemented `/ticket` + `/ticket-pilot` coexistence model. Part 4 is
historical risk analysis except where a later note records the implemented
resolution.

Supporting API research lives in its own files —
[components-v2-in-hikari.md](components-v2-in-hikari.md),
[hikari-lightbulb-versions.md](hikari-lightbulb-versions.md),
[component-dispatcher.md](component-dispatcher.md). This file is the proposal;
none of those references replaces the operations guide for rollout.

---

# PART 1 — RESEARCH FINDINGS

## 1.1 The premise: does the migration buy what we think?

**Threads do not count against the 500-guild-channel limit.** Discord, verbatim:
*"Threads do not count against the max-channels limit in a guild, but there is a
limit on the maximum number of active threads in a guild."*
([topics/threads](https://docs.discord.com/developers/topics/threads))

**The 50-per-category limit: inference, not fact.** No document states it.
The reasoning is structural and high-confidence: a thread's `parent_id` is a
text/forum channel, never a category, and threads are excluded from
`GET /guilds/{id}/channels` — the enumeration the category cap is computed over.

**The active-thread cap is ~1000, and it is NOT in Discord's docs.** Error codes
`160006` / `160007` exist, so a ceiling is enforced; the figure comes from two
community sources. Archived threads are unlimited and do not count.

### Adjudication: capacity is a weak justification for this migration

Guild is 125/500 channels. Lifetime tickets 361, open 23. Against 500 channels
and ~1000 active threads, neither ceiling is close.

**The one real capacity constraint is the FWA category at 50/50** — and
`handlers.py:95` hard-codes `remaining_slots = 50 - used_slots`, failing closed
at zero (`handlers.py:235`). So FWA ticket creation is blocked *today*.

But that is fixable in five minutes by adding a second FWA category and pointing
`fwa_category` at it. **Migration is not the cheapest fix for the capacity
problem, and should not be justified on capacity.**

The honest justification is **discoverability and workflow** — 125 channels that
never get cleaned up, no queue view, no way to find a historical ticket. That is
a real problem and the dashboard is the real fix. State it that way, or the
project optimises for the wrong thing.

## 1.2 The constraint that shapes everything: no nested threads

**A private thread can only be created in a `GUILD_TEXT` channel.** There is no
endpoint to create a thread inside a thread.
([topics/threads](https://docs.discord.com/developers/topics/threads))

Today each ticket is **two spaces**:

| Space | Who sees it | Purpose |
|---|---|---|
| Channel | Candidate + recruiters | Candidate conversation |
| Private thread under it (`handlers.py:338`) | Recruiters only | Role ping, opening questions, back-channel |

Collapse to one thread per ticket and one of those spaces must go.

**This is a documented, industry-wide casualty — not our oversight.** Two
independent commercial bots hit the same wall:

- **Tickets.bot** lists, on its thread-mode page, that `/notes` is unavailable
  because of a *"Discord limitation [that] prevents staff-only threads"*.
  `/notes` in channel mode creates exactly our private sub-thread.
  ([docs.tickets.bot/features/thread-mode](https://docs.tickets.bot/features/thread-mode))
- **Ticket Tool** sells the auto-created staff private thread as a premium
  channel-mode feature, and its thread-style tickets disable `/add`, `/remove`,
  claiming and permission options.
  ([docs.tickettool.xyz](https://docs.tickettool.xyz/dashboard/panel-configs/thread-style))

The recommended answer is not to lose it but to **relocate** it: ticket thread
for the candidate, plus a parallel staff thread in a separate recruiters-only
parent channel, linked by the bot. That is *more* private than today — the
candidate cannot see the parent channel at all.

## 1.3 What threads take away

| Capability | Channel | Thread |
|---|---|---|
| Permission overwrites | ✅ full | ❌ **none — not a thread field** |
| Add a *role* | ✅ | ❌ users only; role-mention auto-add works only for roles under 100 members, max 10 roles/message |
| Silent member management | ✅ overwrites are silent | ❌ every add/remove emits an **undeletable** system message |
| Rename freely | ⚠️ ~2 per 10 min | ⚠️ same wall ([discordjs#6651](https://github.com/discordjs/discord.js/issues/6651)) |
| Belongs to a category | ✅ | ❌ parent is a channel |
| Slash commands always work | ✅ | ❌ **fail in archived threads** |
| Counts vs 500 | ❌ yes | ✅ no |
| Forum tags | ❌ | ✅ *forum only — see below* |

**Two of these are project-shaping:**

**Archived threads reject application commands.** Discord: *"Users cannot edit
messages, add reactions, use application commands, or join archived threads."*
A ticket idle past its auto-archive window becomes inoperable. Worse, Discord
*shortens* auto-archive timers as a guild approaches the thread cap, and it is
**unverified** whether inactivity-archiving reliably fires a gateway event.
Every thread mutation needs an "ensure unarchived" wrapper, and Mongo — not
Discord's `archived` flag — must be the authority on whether a ticket is open.

**The current role ping is load-bearing, not decorative.** `handlers.py:381`
pings the recruiter role inside the private thread; that mention is *how
recruiters get added*. If the recruiter role ever exceeds 100 members, thread
access silently stops working.

## 1.4 Forum tags are not available to us

Agent A recommended a forum channel with `moderated` status tags — genuinely the
best status mechanism Discord offers, settable at creation, mutable without a
rename, and lockable to `MANAGE_THREADS` holders.

**We cannot use it.** Forum channels contain only public threads. Privacy for a
recruitment ticket therefore has to come from the parent channel's overwrites,
which means every applicant who can see the forum can read every other
applicant's ticket, including denials.

The [3-year-old request for private threads in forums](https://github.com/discord/discord-api-docs/discussions/5089)
is still unanswered by Discord. No mainstream ticket bot offers a forum mode.

**Consequence:** status cannot live in a tag. And it cannot live in the thread
name either, because renames hit ~2 per 10 minutes *and fail silently* — the
call just hangs. **Status lives in Mongo and is rendered by the dashboard.**
That is not a limitation of the dashboard; it is the argument for it.

## 1.5 What our stack can actually build

Full detail in [components-v2-in-hikari.md](components-v2-in-hikari.md). The
headline:

- **Components V2 landed in hikari 2.3.0.** Every builder we use exists at
  2.3.5, plus an unused `FileComponentBuilder`. **Upgrading buys zero V2
  capability.**
- **`ModalActionRowBuilderComponentsT = TextInputBuilder`** — modals are
  text-input only, at 2.3.5 *and* 2.5.0. `LabelComponentBuilder` does not exist
  in any hikari version. So every modal component Discord shipped since Aug 2025
  (selects, Text Display, file upload, radio, checkbox) is **unreachable from
  Python**. The "one modal captures all filter axes atomically" pattern is not
  buildable.
- **lightbulb has no Components V2 support at any version** — `Menu` builds only
  action rows. The custom dispatcher is the only path to a V2 UI and must not be
  "migrated to `Menu`".
- **The "bug in 2.3.4+" folklore is retired.** The real constraint is
  `hikari-lightbulb==3.0.3` declaring `hikari~=2.3.1` (`>=2.3.1, <2.4.0`).

## 1.6 Concurrency: Discord offers nothing

Five workstreams converged independently: no ETags, no conditional requests, no
idempotency keys, no locking. Every `PATCH` is unconditional last-write-wins.
Discord's own docs disclaim consistency and instruct apps to be idempotent while
providing no mechanism to help.

**All conflict handling is ours.** This was a defect at proposal time and is now
resolved: both runtimes use a conditional open-to-terminal transition in their
own authority. A losing concurrent action cannot silently overwrite the
winner.

**Claiming can only ever be advisory.** Tickets.bot states flatly that *"Discord
does not allow threads to be claimed"*; Ticket Tool disables claiming on thread
tickets. We can record and display a claim; we cannot stop a second recruiter
typing.

## 1.7 Search: Discord cannot find our history

No list endpoint filters by tag, status, name or creator.
`GET /guilds/{id}/threads/active` has **no pagination**. Archived listing is
per-channel and reverse-chronological only. Users report thread content is not
reliably searchable and `in:` does not accept threads.

**One genuinely new capability:** `GET /guilds/{id}/messages/search` became
available to bots in the [19 March 2026 changelog](https://docs.discord.com/developers/change-log)
— an eight-year-old "low priority" request. Caps at ~10k reachable results,
needs `MESSAGE_CONTENT`, async indexing (error `110000`), no tag filter. Useful
as a human convenience; **not a system of record.**

## 1.8 Attachment durability

Attachment durability remains an open live-ticket risk. Terminal legacy
cloning separately audits source attachments and requires the exact
`LOSS-...` acknowledgement for unavailable files. The shipped runtime has no
close command or re-host-at-close workflow.

## 1.9 Our own foundations

**The dispatcher has no failure semantics.** `user_only` is declared and used
zero times — there is no authorization mechanism at all. No error boundary: a
raising handler after `defer(edit=True)` leaves the user with a button that
un-presses and does nothing, forever, with no error. No unknown-action guard: a
renamed action crashes every existing message referencing it, and components
never expire. The `if not kw: return` expiry guard is dead code. Full list in
[component-dispatcher.md](component-dispatcher.md), including a **live inert
button in production** (`manage_fwa_data:main`).

At proposal time, legacy ticket documents lived in `button_store` beside
ephemeral state. Shipped coexistence keeps legacy ticket rows in
`button_store`; thread-v2 tickets and completed clones live in `tickets`.

---

# PART 2 — DASHBOARD DESIGN

## 2.1 The two jobs, deliberately different

| | The Queue | The Archive |
|---|---|---|
| Question | "What needs me now?" | "What happened with X?" |
| Default scope | `status: open` only (23 today) | everything, forever (361+) |
| Entry | `/ticket-pilot console` | `/ticket-pilot history member:@user`, `/ticket-pilot find` |
| Feel | Dense, actionable, live | Sparse, precise, read-only |
| Backed by | One indexed Mongo query | Indexed query + optional Discord message search |

They live in one dashboard but are reached differently, because conflating them
is what makes ticket UIs bad. The queue is a *worklist*; the archive is a
*lookup*. A lookup does not need browsing — it needs a good query and ten
results with jump links.

## 2.2 Structural rule: shared message stateless, per-user panels ephemeral

Agents B and F reached this independently.

State keyed by `action_id` is a property of the **message**, not the viewer. Two
recruiters on one shared message overwrite each other's filters — and the
dispatcher's `ctx.respond(..., edit=True)` edits the shared message itself.

So:

```
#recruiter-hub  ─ ONE persistent, never-edited-by-interaction message
                  ├ Text: live counts (bot edits this on state change only)
                  └ Button: "Open Console"  ← the only interactive element
                                │
                                ▼  every click mints a fresh action_id
                          EPHEMERAL per-user panel
                          (all filtering, paging, drilling happens here)
```

Discord scopes ephemerals per-user for free. Entry-point action names become a
tiny, permanently-supported API; everything else can be renamed freely.

## 2.3 The component budget

40 components per message; **~4000 characters of text message-wide** (not
official; corroborated by two independent third parties — this binds first).

| Row style | Components/row | Max rows |
|---|---|---|
| Section + Text + Button accessory | 3 | ~8 |
| Text Display lines | ~0 | ~45 |
| **String select options** | **2 per 25** | **25** |

**Select-as-result-list is the density winner**: 25 fully-labelled,
individually-actionable tickets for 2 components. Each option carries a 100-char
label, 100-char description and a custom emoji. 361 tickets = 15 pages; one
page-jump select reaches all 15 in a click.

## 2.4 Pragmatic version — recommended

> **Superseded.** The decided build is max-flash, not pragmatic, and the
> filter row below (Status/Type/Recruiter as three selects on the shared
> console) was relocated to the ephemeral results panel and dropped to two
> axes (no recruiter/claim filter). See
> [ticket-console.md](ticket-console.md) §2–§4. Kept here for the component
> budget accounting, which is still the right way to think about the cost of
> any row you add.

```
╭─ Container (accent = RED_ACCENT) ─────────────────────────────╮
│ ┌ Section ─────────────────────────── [Thumbnail: guild icon] │
│ │ ### Ticket Console                                          │
│ │ ▸ Open: `23`   ▸ FWA `9` · Main `14`                        │
│ │ ▸ Unclaimed: `6`   ▸ Oldest: <t:...:R>                      │
│ └                                                             │
│ ── Separator ─────────────────────────────────────────────    │
│                                                               │
│ [ Select: 25 open tickets, newest first ]                     │
│   🆕 FWA #187 · Ruggie          — unclaimed · 2 days ago      │
│   🔵 Main #186 · SomeUser       — @Recruiter · 4 hours ago    │
│   ⚠️ FWA #180 · Another         — unclaimed · 9 days ago      │
│                                                               │
│ ── Separator ─────────────────────────────────────────────    │
│ [Status ▾]  [Type ▾]  [Recruiter ▾]        ← 3 rows, 6 comps  │
│ [◀] [▶] [🔍 Search] [⟳ Refresh]            ← 1 row, 4 comps   │
│ [Media: Red_Footer.png]                                       │
╰───────────────────────────────────────────────────────────────╯
```

Budget: container 1 + section 2 + thumbnail 1 + separators 3 + result select 2 +
filter rows 6 + nav row 5 + footer 1 = **21 of 40.** Comfortable headroom.

**Selecting a ticket** replaces the panel with a detail view: the ticket's
answers, who claimed it, age as `<t:…:R>`, a **Jump to Thread** link button, and
`[Claim] [Approve] [Deny] [Back]`. Approve/Deny run the conditional write; Deny
opens the existing text-input modal for a custom reason.

**Filters** are three string selects, `min_values: 0` so each is clearable. Each
change is one interaction that re-renders the ephemeral. State persists in the
panel's own `component_state` document, so paging preserves filters.

**Search** is a button → modal → single text input (all hikari permits) → a
results panel in Archive mode, unrestricted by status.

## 2.5 Maximum-flash version, and what it costs

> **This is the one that got built.** Decision reversed from the 2.6
> recommendation below — see [ticket-console.md](ticket-console.md) §3. The
> chart replaces the stat Section rather than sitting alongside it, which is
> cheaper in components than either version anticipated.

Everything above, plus:

| Addition | Cost / risk |
|---|---|
| **Server-rendered PNG chart** (throughput, age distribution, per-recruiter load) regenerated on each filter change, shown via Media Gallery | Image pipeline, render latency inside the defer budget, upload bandwidth. **Highest visual payoff on the platform; highest new dependency.** Cloudinary already present. |
| **ANSI code-block table** — coloured, column-aligned monospace rows | ~60 chars/row against the 4000 budget; **not in official Discord docs**; degrades to monochrome on old mobile; forces horizontal scroll past ~55 cols |
| **State-driven `accent_color`** — green/amber/red by oldest unclaimed age | Free. Do this regardless. |
| **Container `spoiler`** over candidate PII | Free. One boolean. |
| **Animated custom emoji** as live status glyphs in select options | Needs boosted guild for upload |
| **Per-recruiter avatars** as Section thumbnails | Caps rows at ~8; conflicts with select-as-list |
| **`<t:…:R>` everywhere** | Free, and the only self-updating element on the platform |

**Honest assessment:** the chart is the only item that genuinely changes how the
dashboard reads, and it is also the only one that adds a real dependency and a
latency risk. Everything else in the flash column is either free (accent colour,
spoiler, relative timestamps — take all three now) or a trade against density.

**Original recommendation (2026-08-02): ship pragmatic + the three free flash
items, add the chart later once the queue is proven. Reversed 2026-08-17** —
the chart ships in the first build, as the header, replacing the stat Section
rather than adding to it (see [ticket-console.md](ticket-console.md) §3). Do
not build the ANSI table — undocumented, mobile-hostile, and it competes with
the select-as-list for the same screen space. That part didn't change.

## 2.6 Handling 361+ without hitting limits

- Queue view never renders more than 25 rows — it is `status: open`, currently 23.
- Archive search returns **top 10 with jump links**, never a browsable list.
- Paging is cursor-based (`_id`/`created_at`), stored in `component_state`, with
  an offset-derived "Page 3 of 15" label for legibility.
- Growth is bounded by the query, not by the collection. At 5,000 tickets the
  queue view is unchanged and only the archive count moves.

---

# PART 3 — HISTORICAL MIGRATION & ARCHITECTURE

> **Superseded operator design.** The shipped system keeps legacy `/ticket`
> rows in `button_store` and thread-v2 `/ticket-pilot` rows in `tickets`.
> Shared slot and counter records coordinate uniqueness; ticket rows are not
> copied or dual-written between authorities. See the
> [operations guide](ticket-console-operations.md) before changing rollout.

## 3.1 Implemented sequencing and authority boundary

The parallel runtime removes the proposal's extraction prerequisite. Configure
the v2 parents and console, bind a restricted pilot beside the unchanged public
legacy panel, then move through the guarded rollout phases in §3.4. Legacy
tickets remain in `button_store`; thread-v2 tickets remain in `tickets`.
Shared slot and counter records coordinate duplicate-open prevention and ticket
numbers without copying ticket rows between the two authorities.

## 3.2 V2 data model scope

The `tickets` collection contains only thread-v2 tickets and completed terminal
clones. It uses `location.id` and `location.staff_space_id` for the candidate
and staff thread pair. Live legacy channel rows stay outside this model and
outside the v2 console. The [operations guide](ticket-console-operations.md)
owns the deployed authority contract.

## 3.3 Thread ticketing end to end

| Step | Legacy `/ticket` | Thread v2 `/ticket-pilot` |
|---|---|---|
| Authority | `button_store` | `tickets` |
| Create | `create_guild_text_channel` + overwrites | `create_thread(GUILD_PRIVATE_THREAD)` in a ticket parent channel |
| Candidate access | permission overwrite | `add_thread_member` |
| Recruiter access | role overwrite | Recruiter role requires `VIEW_CHANNEL`, `READ_MESSAGE_HISTORY`, `SEND_MESSAGES_IN_THREADS`, and `MANAGE_THREADS`; creation also mentions the role |
| Staff back-channel | private thread under the channel | Parallel thread beneath the configured private recruiter-only staff parent, cross-linked in Mongo |
| Questionnaire | `GuildChannelCreateEvent` → monitor | posted inline at creation (threads fire `GuildThreadCreateEvent`, not the channel event) |
| Status | channel rename ✅/❌ | **Mongo only** — never rename |
| Approve/Deny | Conditional terminal transition in the legacy authority | Conditional terminal transition in the v2 authority |
| *(no "close")* | rename, leave forever | `archived: true, locked: true` in one PATCH, background-only — see below |

`locked` matters: archive alone means any stray message silently reopens a
resolved ticket and re-consumes an active slot. Locked returns error `160005`
instead.

> **2026-08-17: there is no "close."** Decided in console review — tickets
> are permanently `approved` or `denied`, never a status meaning gone, and
> the console never renders "closed." The implemented runtime locks and
> archives both terminal threads. Console jump links open them read-only; they
> remain locked and archived and are not automatically unarchived. Full
> reasoning is in [ticket-console.md](ticket-console.md) §7.

## 3.4 Implemented phase routing

The shipped runtime does not use `ticket_mode`. It loads two command groups and
keeps their authorities separate: `/ticket` for legacy channel tickets and
`/ticket-pilot` for thread-v2 tickets. A guarded rollout record routes only new
intake:

| Phase | New intake |
|---|---|
| `legacy_only` | Existing public panel routes to legacy; pilot is disabled. |
| `prepared` | Legacy-only; bindings and parents have passed validation. |
| `pilot` | Public panel stays legacy; the exact allowlisted pilot panel routes to v2. |
| `thread_default` | Existing public panel routes to v2; legacy tickets remain operable. |
| `rollback_legacy` | New public intake returns to legacy; existing v2 tickets remain operable. |
| `thread_only` | Public intake routes to v2 after every legacy drain blocker reaches zero. |

Promotion and rollback are commands, not manual Mongo writes. Use
`/ticket-pilot rollout-promote` and `/ticket-pilot rollout-rollback` as
documented in the [operations guide](ticket-console-operations.md).

## 3.5 Fixed store authorities

There is no bulk Mongo cutover during coexistence. Open and terminal legacy
rows remain authoritative in `button_store`; v2 writes only to `tickets`. A
selected terminal legacy ticket may be cloned individually with
`/ticket-pilot migrate-legacy`, creating a destination v2 row and archived
thread pair without modifying or replacing the source.

## 3.6 Implemented rollout progression

The executable progression is `legacy_only` → `prepared` → `pilot` →
`thread_default` → `thread_only`. A confirmed rollback from `prepared` returns
to `legacy_only`; a rollback from a live v2 phase enters `rollback_legacy`.
Returning from rollback repeats prepare, pilot, and promote. Entering
`thread_only` additionally requires zero open legacy tickets, active legacy
slots, and pending legacy workflows.

---

# PART 4 — RISKS & OPEN QUESTIONS

## 4.1 Risks, by severity

| # | Risk | Mitigation |
|---|---|---|
| 1 | **Legacy reconciliation could mistake threads for missing channels.** | Resolved by separate legacy/v2 repositories and command surfaces; legacy reconciliation does not own v2 rows. |
| 2 | **A dashboard handler could delete a ticket record through the old shared-state convention.** | Resolved with dedicated component state and v2 action namespacing. |
| 3 | **Losing the recruiter back-channel.** Two commercial bots lost it in this exact migration. | Resolved: every v2 ticket receives a parallel staff thread in the configured private staff parent. |
| 4 | **Tickets become inoperable when archived** — an original-design concern. | The shipped v2 flow acts before terminal archive, then keeps terminal pairs locked, archived, and available read-only. Durable recovery temporarily repairs only pending bot-owned work. |
| 5 | **Silent status overwrite** — approve could clobber deny. | Resolved: both runtimes use conditional terminal transitions; only one decision wins. |
| 6 | **A legacy clone cannot fetch a source attachment.** | The read-only preview audits attachment loss; confirmation requires the exact reported `LOSS-...` token. The source remains unchanged. |
| 7 | **A large recruiter role cannot rely on role-mention auto-add.** | Resolved by requiring `MANAGE_THREADS` on the configured recruiter role; parent validation enforces it. |
| 8 | **~1000 active-thread cap is undocumented** and Discord shortens auto-archive as you approach it. | The shipped runtime locks and archives each terminal pair. Console links keep it read-only and do not auto-unarchive it. |
| 9 | **System-message spam** on every thread member add. Undeletable. | Set membership once at creation; never use add/remove for claiming. |
| 10 | **`SEND_MESSAGES` does nothing in threads** — candidates need `SEND_MESSAGES_IN_THREADS`. | `/ticket-pilot configure-threads` validates configured parent and recruiter permissions, `/ticket-pilot thread-config` revalidates them, and intake validates the applicant before creating threads. |
| 11 | Thread renames fail *silently* at ~2/10min. | Never rename. Status in Mongo. |
| 12 | Parent channel deletion likely destroys all child threads, irreversibly. | Treat the ticket parent channel as protected infrastructure. |

## 4.2 DECISIONS — settled 2026-08-02

| # | Decision | Consequence |
|---|---|---|
| 1 | **Parallel staff thread** in a recruiters-only channel, bot-linked via `location.staff_space_id` | Two Discord objects per ticket; dashboard surfaces both |
| 2 | **FWA 50/50 fixed independently** (second category + repoint `fwa_category`) | Migration is **purely a UX project, no urgency**. Take phases in order. |
| 3 | **`abandoned` was proposed as a real state.** | Not implemented. Thread v2 stores only `open`, `approved`, or `denied`; rollout does not backfill or reclassify legacy rows. |
| 4 | **Advisory claiming accepted** | Social convention at this size; Discord cannot enforce it regardless |
| 5 | ~~**Charts skipped for now**, revisit at phase 5~~ **REVERSED 2026-08-17** by decision 7 | The chart ships in v1 as the console header. Pillow is already a dependency and the image is a message attachment, so it added nothing new after all. |
| 6 | **hikari+lightbulb upgrade is a separate track, after phase 2** | Coupled move (2.5.0 + 3.2.5); must not ride along with ticketing |

The original proposal rejected a read-only dashboard over legacy channel
tickets. The shipped v2 console likewise queries `tickets`, not live
`button_store` rows.

## 4.2b DECISIONS — console review, settled 2026-08-17

Full detail and reasoning in [ticket-console.md](ticket-console.md). Summary:

| # | Decision | Consequence |
|---|---|---|
| 7 | **Max-flash, not pragmatic.** No two-tier build. | Chart ships in v1, replaces the stat Section rather than adding to it. |
| 8 | **One console, no Main/FWA split.** Rejected explicitly. | Single shared message; type filtering lives in search, not in a second console. |
| 9 | **No "Open Console" gateway.** The shared message's picker and Find-a-ticket button are the entry points directly. | One fewer click; structural rule (state on the message, not the viewer) still holds. |
| 10 | **Manual refresh button dropped.** | `refresh_hub()` already runs on create/approve/deny; a button had no state left to fix. |
| 11 | **Search: Discord ID / player tag / username, nothing else.** Recruiter-claim filter dropped entirely. | Simpler modal, matches decision 12. |
| 12 | **No claiming surfaced in the console.** "We don't care what the recruiter claimed." | Backend `claimed_by`/`claimed_at` (decision 4) untouched for now — open question, §4.3 item 4. |
| 13 | **Blacklist is binary, no "maybe" tier.** Two more flags added as non-blocking cautions: denied-before, not-loyal-to-WU. | New small `ticket_flags`-style collection, not designed before now — see [ticket-console.md](ticket-console.md), Related. |
| 14 | **Status/Type filters cannot live inside the "Find a ticket" modal** — hikari has no Label builder, so Discord's Aug-2025 modal-select support is unreachable (the wall established in §1.5). Relocated to the ephemeral results panel as two message selects. | Corrects a mockup mistake before it became a build mistake. |
| 15 | **`/fwa chocolate` is a link-out, not a lookup** — confirmed against `extensions/commands/fwa/chocolate.py`. A human reads the ban status and records it as a flag. | Corrects a second mockup mistake; the flag record's shape (`addedBy`, `checkedAt`, `source`) was already right for this. |
| 16 | **Nothing is ever "closed."** Tickets are permanently `approved`/`denied`; the thread is never renamed to imply done, never deleted. | Implemented: the runtime locks and archives both terminal threads, while console links keep them available read-only. See [ticket-console.md](ticket-console.md) §7. |
| 17 | **Ticket-history auto-detect** — any repeat Discord ID/player tag gets a staff-thread panel with jump links, independent of the flag system. Fires for everyone with history, not just flagged people. | New behavior, not in the original proposal at all. |
| 18 | **The flag is labelled "Blacklisted," not "On blacklist."** | Copy change only; applied to console copy, the chart pill and the mockup. |
| 19 | **Chart palette is vibrant, and colorblind/CVD validation is explicitly NOT a requirement.** The earlier `dataviz` six-check palette (`#43a25a`/`#7b83f0`/`#e0656a`) is rescinded. Flag colors are sampled from the supplied artwork. | Reverses a self-imposed constraint that was never asked for. The only standing audience requirement is plain-English copy. See [ticket-console.md](ticket-console.md) §3.2. |
| 20 | **Chart iconography is supplied PNG artwork or hand-drawn PIL shapes — never emoji rendered through a font.** Five assets committed to `assets/tickets/`. | Color-emoji support is unreliable across Pillow/server font setups; a glyph that renders locally can be a box on the deploy box. See [ticket-console.md](ticket-console.md) §3.4. |
| 21 | **Terminal legacy channel tickets can be cloned into threads** via webhook impersonation — single target server, staff-thread parity, archive immediately. | Implemented as a source-read-only, resumable `/ticket-pilot migrate-legacy` flow, hard-capped at 1–5 selected tickets before pilot approval. There is no §3.5 bulk store conversion. |

## 4.3 Original open questions (superseded above)

1. ~~**The back-channel.**~~ **Settled 2026-08-17**: parallel staff thread,
   recommended option. It's also where the flag alerts and history panel
   from [ticket-console.md](ticket-console.md) render.
2. **Is the FWA 50/50 category being fixed independently?** If yes, the
   migration is purely a UX project and can move at its own pace. If the
   migration *is* the fix, phase 3 becomes urgent and I'd want to reorder.
3. ~~**`abandoned` status.**~~ **Settled by implementation:** v2 uses only
   `open`/`approved`/`denied`; there is no abandoned-state backfill or filter.
   See [ticket-console.md](ticket-console.md) §9.
4. ~~**Advisory claiming.**~~ **Settled by the runtime split:** the v2 console
   and `/ticket-pilot` have no claim/release workflow. `/ticket claim` and
   `/ticket release` remain legacy-only commands. See
   [ticket-console.md](ticket-console.md) §9.
5. ~~**Chart rendering** in phase 5, or not at all?~~ **Settled 2026-08-17**:
   phase 1 (first build), not phase 5. See decision 7 above.
6. **The hikari/lightbulb upgrade** — separate track now, later, or never? Not
   needed for capability; four upstream fixes target the July 29 failure mode.
   Re-confirmed 2026-08-17 that 2.5.0 would not have unblocked the
   modal-select pattern anyway (decision 14) — no new urgency from this
   review.

## 4.4 What I could not determine

- **Whether inactivity auto-archive fires `THREAD_UPDATE`.** Discord's docs never
  say. Two issues suggest lazy/asymmetric behaviour. **Settled by:** creating a
  thread with a 60-minute auto-archive on a test guild and logging events for
  two hours.
- **The exact active-thread cap.** Not in Discord's docs; 1000 is community-
  sourced. **Settled by:** Discord support, or empirically (undesirable).
- **Whether select-option text counts against the 4000-char component budget.**
  If exempt, select-as-list is nearly free. **Settled by:** one test message.
- **Why the box ran 2.3.5 despite commit `397e3ba`.** The lightbulb pin explains
  it mechanically but cannot distinguish "pip re-resolved" from "the command was
  never run". **Settled by:** the venv's pip history on the Hetzner box.
- **Whether `applied_tags` is returned by `fetch_active_threads`.** Moot for us
  since forums are ruled out, but noted.
