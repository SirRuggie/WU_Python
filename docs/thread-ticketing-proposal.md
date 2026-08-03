# Thread-based ticketing + console dashboard — research & proposal

Research deliverable, 2026-08-02. Seven parallel research workstreams, findings
adjudicated against primary sources. **No code was written and no existing
behaviour was changed.**

Durable API facts extracted from this research live in their own files —
[components-v2-in-hikari.md](components-v2-in-hikari.md),
[hikari-lightbulb-versions.md](hikari-lightbulb-versions.md),
[component-dispatcher.md](component-dispatcher.md),
[ticket-data-model.md](ticket-data-model.md). This file is the proposal.

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

**All conflict handling is ours.** `find_one_and_update` with a status
precondition; the loser gets an ephemeral naming who won and when. The correct
pattern already exists in this repo at `manage.py:465` — it was simply never
applied to approve/deny, which today are unconditional `$set` (`close.py:230`).
An approve silently overwrites a deny. A dashboard with adjacent buttons turns
that from rare into routine.

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

## 1.8 The archive rots unless we intervene

Discord CDN attachment URLs have been signed and expiring (~24h) since late
2023. Any transcript that stores Discord URLs is already decaying. For CoC
recruitment — base screenshots, war logs — **attachment bytes must be
re-hosted at ticket close**, not linked. Cloudinary is already a dependency.

## 1.9 Our own foundations

**The dispatcher has no failure semantics.** `user_only` is declared and used
zero times — there is no authorization mechanism at all. No error boundary: a
raising handler after `defer(edit=True)` leaves the user with a button that
un-presses and does nothing, forever, with no error. No unknown-action guard: a
renamed action crashes every existing message referencing it, and components
never expire. The `if not kw: return` expiry guard is dead code. Full list in
[component-dispatcher.md](component-dispatcher.md), including a **live inert
button in production** (`manage_fwa_data:main`).

**Ticket documents live in `button_store`** alongside ephemeral component state,
unindexed, unpruned. See [ticket-data-model.md](ticket-data-model.md).

---

# PART 2 — DASHBOARD DESIGN

## 2.1 The two jobs, deliberately different

| | The Queue | The Archive |
|---|---|---|
| Question | "What needs me now?" | "What happened with X?" |
| Default scope | `status: open` only (23 today) | everything, forever (361+) |
| Entry | `/ticket console` | `/ticket history @user`, `/ticket find` |
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

**Recommendation: ship pragmatic + the three free flash items. Add the chart as
a phase-4 enhancement once the queue is proven.** Do not build the ANSI table —
undocumented, mobile-hostile, and it competes with the select-as-list for the
same screen space.

## 2.6 Handling 361+ without hitting limits

- Queue view never renders more than 25 rows — it is `status: open`, currently 23.
- Archive search returns **top 10 with jump links**, never a browsable list.
- Paging is cursor-based (`_id`/`created_at`), stored in `component_state`, with
  an offset-derived "Page 3 of 15" label for legibility.
- Growth is bounded by the query, not by the collection. At 5,000 tickets the
  queue view is unchanged and only the archive count moves.

---

# PART 3 — MIGRATION & ARCHITECTURE

## 3.1 Sequencing — this is the part with a hard constraint

```
1. Fix the dispatcher          ← blocks everything
2. Extract tickets from button_store  ← blocks the flag
3. Build thread ticketing behind a flag
4. Build the dashboard
5. (separate track) hikari+lightbulb upgrade
```

**Why 1 blocks everything.** The natural custom_id for a ticket action is
`ticket_view:ticket_{channel_id}`. Write that and `components.py:86` loads the
*ticket document* as handler kwargs — silently, no error, every handler takes
`**kwargs`. And the house convention ends handlers with
`delete_one({"_id": action_id})` (`close.py:471`, `:563`, `:688`). One handler
in the established style permanently deletes a ticket record. This is the most
obvious way to write the feature.

The fix is ~50 lines inside `components.py`, **zero changes to the ~120 existing
call sites**, roughly a day: error boundary with ephemeral followup + a
correlation ref; unknown-action guard with a `deprecated_alias_of` escape hatch;
real expiry detection via signature introspection; group routing on the routing
key; a dedicated `component_state` collection with a `button_store` fallback;
declarative `allowed_roles` / `owner_field` defaulting to today's open
behaviour.

One constraint rules out the naive version: about a third of live custom_ids
carry a semantic `action_id` that was never a state key (`create_ticket:main`,
`clan_database:`, `edit_clan:role_id_#TAG`). A blanket "state missing → refuse"
breaks live ticket creation on day one. Signature introspection distinguishes
the cases without editing decorators. **Ship the expiry check in log-only mode
for a week first.**

**Why 2 blocks the flag.** You cannot TTL-prune `button_store` while tickets
live in it — the only date field on ephemeral docs is `created_at`, which is
also the ticket's creation date. A TTL index deletes ticket history. Extraction
converts an unfixable problem into a one-line index. Doing it *before* the
thread work keeps coexistence at **one collection × two venues** instead of a
2×2 matrix of collection × era.

## 3.2 The unified data model

One `tickets` collection serving both eras. `_id` preserved verbatim
(`ticket_{channel_id}`) so every sync is an idempotent upsert and rollback is a
code deploy, not a data restore.

```javascript
{
  _id: "ticket_1395400463897202738",   // UNCHANGED from today
  schema_version: 2,
  venue: "channel" | "thread",          // the era discriminator
  location: {
    id:        <the ticket container>,  // channel OR thread — the jump target
    parent_id: <category OR parent channel>,
    staff_space_id: <private thread OR staff thread in recruiter channel>,
  },
  channel_id, thread_id, category_id,   // legacy mirrors, kept during coexistence
  ticket_type: "main" | "fwa",
  ticket_number: <int>,
  user_id, username, username_lower, display_name,
  guild_id,                             // NOT stored today; needed for jump links
  status: "open" | "approved" | "denied" | "closed",
  created_at, resolved_at,
  claimed_by, claimed_at,               // NEW — advisory claiming
  handled_by, handled_by_name,          // NEW — unified terminal actor
  rev: 0,                               // optimistic concurrency
  audit: [],
  // all original approve/deny fields preserved unchanged
}
```

`location.id` is the key insight: the jump link is
`discord.com/channels/{guild_id}/{location.id}` for **both** eras, identical
code path. `venue` is rendered as a badge only. One index
`{"location.id": 1, unique: true}` serves both.

**Backfill is additive-only** — every original field keeps its name and value;
the inverse is a `$unset` of the new keys. Note `manage.py:263` documents that
IDs have been stored as both `int` and `str` historically, so the backfill must
coerce before any unique index.

**Indexes:** `{status:1, created_at:-1}`, `{ticket_type:1, status:1,
created_at:-1}`, `{username_lower:1}`, `{user_id:1, created_at:-1}`,
`{claimed_by:1, status:1}`, `{channel_id:1}` (unique), `{"location.id":1}`
(unique). Also, separately: `{challenge_type:1, channel_id:1, status:1}` on
`button_store` — the goblin-challenge lookup is an unindexed collection scan
executed **on every guild message**, quietly the hottest query in the codebase.

## 3.3 Thread ticketing end to end

| Step | Channel era (unchanged) | Thread era |
|---|---|---|
| Create | `create_guild_text_channel` + overwrites | `create_thread(GUILD_PRIVATE_THREAD)` in a ticket parent channel |
| Candidate access | permission overwrite | `add_thread_member` |
| Recruiter access | role overwrite | role mention (auto-adds, <100 members) **or** `MANAGE_THREADS` on the recruiter role |
| Staff back-channel | private thread under the channel | **parallel thread in `#recruiter-workroom`**, cross-linked in Mongo |
| Questionnaire | `GuildChannelCreateEvent` → monitor | posted inline at creation (threads fire `GuildThreadCreateEvent`, not the channel event) |
| Status | channel rename ✅/❌ | **Mongo only** — never rename |
| Approve/Deny | `$set` | `find_one_and_update` with `status: "open"` precondition |
| Close | rename, leave forever | `archived: true, locked: true` in one PATCH |

`locked` matters: archive alone means any stray message silently reopens a
resolved ticket and re-consumes an active slot. Locked returns error `160005`
instead.

## 3.4 The feature flag

**Lives in `mongo.ticket_setup._id: "config"`** as `ticket_mode: "channel" |
"thread"`, defaulting to `"channel"`. The config doc is re-read on every
invocation (`handlers.py:185`) — never cached — so a flip takes effect
immediately with no restart. The `ticket_config` global loaded at
`__init__.py:29` is **read by nothing anywhere in the repo**; it is dead and
should be deleted rather than wired into this.

**Exactly one existing file needs a functional edit.** A 3-line branch after the
config read at `handlers.py:185`:

```python
if config.get("ticket_mode", "channel") == "thread":
    return await create_thread_ticket(ctx, action_id, config, bot, mongo)
```

Everything below stays untouched. The shared cooldown / cleanup / defer block
above it runs for both paths, which is what you want. Plus one import line in
`__init__.py`. Everything else is new files.

**Do not change the custom_ids in `setup.py`.** The entry embed is a persistent
message posted months ago; branching inside the handler is the only option that
doesn't require re-posting it, and users clicking the old message still route
correctly.

### What the flag controls, what it doesn't

It controls **which system handles a NEW ticket**. It does not migrate anything.
Tickets created under channel mode stay channels and remain fully operable —
`/ticket approve` and `/ticket deny` look up by `{"type":"ticket", "channel_id":
ctx.channel_id}` (`close.py:106`, `:218`), and **inside a thread `ctx.channel_id`
IS the thread id**, so both eras resolve through the same code path with zero
changes. The channel-rename step throws harmlessly on threads and is already
wrapped.

This matches industry practice: Tickets.bot documents that *"Tickets created in
channel mode remain as channels… Only new tickets will use the currently active
mode."*

### Rollback

Flip `ticket_mode` back to `"channel"` — one Mongo write. Live thread tickets
stay resolvable because approve/deny key off the document, not the mode. No data
migration in either direction. Nothing is stranded.

### ⚠️ The one thing that must be gated before the flag is ever flipped

**`/ticket cleanup-ghosts` becomes a data-destroying command.**
`manage.py:410-416` builds `live_ids` from `fetch_guild_channels`, **which does
not return threads**, then marks every open ticket not in that set as
`denied` / `channel_deleted` (`manage.py:464`). Flip the flag, run
cleanup-ghosts, and **every live thread ticket is silently denied.** Same defect
in `/ticket diagnostics` and `/ticket fix-mismatched`.

Gate all three on `venue`, or have them union `fetch_active_threads`. This is
not optional and it is not a phase-4 item.

## 3.5 The 361 existing documents

**338 of 361 are terminal** (273 denied, 64 approved, 1 closed) and no code path
writes to a non-open ticket — verified: every mutation filters `status: "open"`.
They can be copied at any time with zero coordination and zero drift risk.

**23 are open**, all with live channels, 0 ghost rows, 0 orphaned channels. That
is the entire drift surface, and it is small enough to enumerate by hand.

**Plan:** mongodump first. Copy all 361 into `tickets` non-destructively —
**nothing is deleted from `button_store`**. Verify counts (361 total; 64/1/273/23
by status) before repointing any code. Dual-write for one deploy cycle, then
read `tickets` only. Delete the `button_store` originals months later, after the
flag is gone.

Keep the single `closed` document as-is. It is the sole survivor of the deleted
`/ticket close` command and records a real historical decision — normalising it
to `denied` is the one genuinely irreversible act available in this migration.

## 3.6 Phasing

| Phase | Ships | Status |
|---|---|---|
| **0** | Dispatcher fix. Reconciliation commands gated on venue. | **Partly live** — routing guards + error boundary deployed and proven. Commits 3 & 4 (`component_state`, log-only expiry) **unwritten**. |
| **1** | `tickets` collection + backfill + indexes + dual-write | **Live, soaking** since 2026-08-02 |
| **2** | Approve/deny conditional writes; override path; claiming | **Live, soaking** since 2026-08-02 |
| **3** | Thread ticketing behind `ticket_mode`, off by default | Not started |
| **4** | Console dashboard (pragmatic + free flash) | Not started |
| **5** | Attachment re-hosting; chart rendering; hikari 2.5.0 + lightbulb 3.2.5 | Not started |

**Outstanding before phase 3:** dual-write removal (date-gated, 2026-08-09 at the
earliest), the `back_to_clan_edit` duplicate (delete the *loser* — see
[component-dispatcher.md](component-dispatcher.md)), and phase 0 commits 3 & 4.

Phases 0–2 improve the **existing** system and are worth shipping even if thread
ticketing is abandoned. That is deliberate: nothing before phase 3 is a bet on
the migration.

---

# PART 4 — RISKS & OPEN QUESTIONS

## 4.1 Risks, by severity

| # | Risk | Mitigation |
|---|---|---|
| 1 | **`/ticket cleanup-ghosts` mass-denies live thread tickets.** `fetch_guild_channels` excludes threads. | Gate on `venue` **before** the flag can be flipped. Phase 0. |
| 2 | **A dashboard handler deletes a ticket record** via a `ticket_*` action_id + the house `delete_one` convention. | Dedicated `component_state` collection. Phase 0. |
| 3 | **Losing the recruiter back-channel.** Two commercial bots lost it in this exact migration. | Parallel staff thread in a recruiters-only channel. Decide before phase 3. |
| 4 | **Tickets become inoperable when archived** — slash commands fail, and the archive event may not fire. | Mongo is authority for open/closed; "ensure unarchived" wrapper; nightly reconciliation sweep. |
| 5 | **Silent status overwrite** — approve clobbers deny. Live today; a dashboard makes it routine. | `find_one_and_update` with precondition. Phase 2. |
| 6 | **Archive rots** — Discord CDN URLs expire ~24h. | Re-host attachment bytes at close. Phase 5. |
| 7 | **Recruiter role exceeds 100 members** → role-mention auto-add silently stops. | Monitor; or grant `MANAGE_THREADS` instead. |
| 8 | **~1000 active-thread cap is undocumented** and Discord shortens auto-archive as you approach it. | Lock+archive on close; alarm well below 1000. |
| 9 | **System-message spam** on every thread member add. Undeletable. | Set membership once at creation; never use add/remove for claiming. |
| 10 | **`SEND_MESSAGES` does nothing in threads** — candidates need `SEND_MESSAGES_IN_THREADS`. | Add to `/ticket diagnostics`. The #1 support ticket every thread-mode bot gets. |
| 11 | Thread renames fail *silently* at ~2/10min. | Never rename. Status in Mongo. |
| 12 | Parent channel deletion likely destroys all child threads, irreversibly. | Treat the ticket parent channel as protected infrastructure. |

## 4.2 DECISIONS — settled 2026-08-02

| # | Decision | Consequence |
|---|---|---|
| 1 | **Parallel staff thread** in a recruiters-only channel, bot-linked via `location.staff_space_id` | Two Discord objects per ticket; dashboard surfaces both |
| 2 | **FWA 50/50 fixed independently** (second category + repoint `fwa_category`) | Migration is **purely a UX project, no urgency**. Take phases in order. |
| 3 | **`abandoned` becomes a real state.** Backfill rule: open + 30d no activity. ~21 of the 23 open tickets qualify | Must not fold into `denied` — that corrupts the denial metric. ⚠️ See wrinkle below. |
| 4 | **Advisory claiming accepted** | Social convention at this size; Discord cannot enforce it regardless |
| 5 | **Charts skipped for now**, revisit at phase 5 | Removes the only new dependency from the dashboard build |
| 6 | **hikari+lightbulb upgrade is a separate track, after phase 2** | Coupled move (2.5.0 + 3.2.5); must not ride along with ticketing |

**Explicitly rejected:** a read-only dashboard over existing channel tickets to
get discoverability early. It is work that gets thrown away at phase 3.

### ⚠️ Wrinkle on decision 3 — "no activity" is not derivable today

Ticket documents carry `created_at` and nothing else temporal (`handlers.py:367`).
There is **no `last_activity_at`**, so "open + 30d no activity" cannot be
evaluated from Mongo alone. Three options, to settle at phase 1:

- **`created_at` as proxy** — "created 30d+ ago and still open". Wrong for a
  ticket that was active last week, but free and needs no API calls.
- **One-off fetch of the 23 open channels' `last_message_id`** for the backfill,
  then record `last_activity_at` going forward. Accurate. 23 fetches is safe —
  this is not the per-ticket loop that got the startup sweep disabled, which ran
  over every channel in the guild.
- **Start recording only, no backfill** — the ~21 get classified by proxy once,
  new tickets get real data.

Recommendation: option 2. It is a bounded one-time cost and it is the only one
that gets the existing 21 right.

## 4.3 Original open questions (superseded above)

1. **The back-channel.** Parallel staff thread in a recruiters-only channel
   (recommended), DB-backed notes surfaced via `/ticket notes`, or accept the
   loss? This shapes phase 3.
2. **Is the FWA 50/50 category being fixed independently?** If yes, the
   migration is purely a UX project and can move at its own pace. If the
   migration *is* the fix, phase 3 becomes urgent and I'd want to reorder.
3. **`abandoned` status** — it does not exist today; the only values ever
   written are `open`/`approved`/`denied`. Introduce it as a real state with a
   backfill rule (e.g. open + no activity 30d), or drop it from the filter list?
4. **Advisory claiming** — acceptable? Discord cannot enforce it.
5. **Chart rendering** in phase 5, or not at all?
6. **The hikari/lightbulb upgrade** — separate track now, later, or never? Not
   needed for capability; four upstream fixes target the July 29 failure mode.

## 4.3 What I could not determine

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
