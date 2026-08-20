# Ticket console — implemented design

Decided 2026-08-17, in mockup review. **Supersedes Part 2 of
[thread-ticketing-proposal.md](thread-ticketing-proposal.md)** — that file's
Part 1 (research), Part 3 (migration/architecture) and Part 4 (risks) still
stand and are not repeated here. This file is the equivalent of
[todo-dashboard.md](todo-dashboard.md) for `/todo`: the "as decided"
description, not the research trail. For setup, daily operation, and recovery,
the [ticket console operations guide](ticket-console-operations.md) is the
operator source of truth.

Design reference: an interactive, clickable HTML mockup
([ticket-console-mockup.html](ticket-console/ticket-console-mockup.html), single self-contained file) was built and
iterated before the runtime shipped, including example ticket threads and bot
panel copy. It remains a visual reference, but the implemented Discord panels
and the operations guide take precedence wherever the mockup differs.

The implementation corrections in §4 and §5 are authoritative. In particular,
search filters do not live in a modal, and Chocolate is always a human-reviewed
link-out rather than an automatic verdict.

---

## 1. The one console, no split

Rejected: a second, FWA-only console. One shared message serves both clan
types. Splitting by type was considered and rejected as bad UX — FWA is ~90%
of volume, so a Main-only *filter* is genuinely useful (it isolates a small
minority); a permanent Main-only *console* is not.

## 2. Architecture — one persistent message, ephemeral drill-down

```
#recruiter-hub  ─ ONE persistent message, bot-owned, in-channel
                  ├ Media Gallery: ticket_overview.png (Pillow chart, §3)
                  ├ String Select: up to 25 open tickets, newest first
                  └ Button: 🔍 Find a ticket
                                │
                  picking a row │  or clicking Find a ticket
                  mints a fresh ▼  action_id, per Structural rule below
                          EPHEMERAL per-user panel
                          (ticket detail, or search results — §4)
```

No "Open Console" gateway button. The original proposal (§2.2) gated *all*
interaction behind one entry button on the shared message; that gate is
gone — the shared message's own picker and search button are the entry
points now. The structural rule underneath is unchanged and still holds:
**state keyed by `action_id` belongs to the message, not the viewer**, so
every personal action (pick a ticket, search, page a result set) opens a
fresh ephemeral panel rather than mutating the shared one.

Discord's real ephemeral banner is part of the contract, not decoration:
"🚫 Only you can see this · Dismiss message" on every drill-down.

**Auto-update, no manual refresh.** Ticket creation, approve/deny, and flag
changes request a hub recount, chart redraw, and persistent-message edit. That
refresh state is durable and retried after a transient Discord failure or bot
restart. A manual "⟳ Refresh" button was removed because operators do not need
to drive recovery. Someone's already-open ephemeral panel is still a snapshot
and does not live-update; reopen the ticket from the hub to read current state.

## 3. The chart replaces the stat Section

The pragmatic/max-flash split in the original proposal (§2.4–2.5) is
resolved: **build max-flash.** Every "free" item in the old flash column
(state-driven accent color, `<t:…:R>` relative timestamps) ships. The one
item flagged as a real dependency — the server-rendered PNG chart — ships
too, as the header, not as an addition to a text Section: it *replaces* the
Section+Thumbnail+stat-text block from §2.4 entirely. One Pillow image
(`ticket_overview.png`, redrawn by `refresh_hub()`, no Cloudinary needed —
it's a message attachment, not a stable-URL asset) carries the open/
approved/denied counts, the by-clan-type breakdown, and the flag counts in
one glance, at a fraction of the component cost of the equivalent Section
markup.

The ANSI-table option from §2.5 is still not built — still undocumented,
still mobile-hostile, still fought the select-as-list for the same screen
space. Nothing changed there.

### 3.1 The chart is a raster attachment — Discord's component rules don't apply

Worth stating plainly because it was a live source of confusion during
review: `ticket_overview.png` is a **PNG attachment**, not components. The
40-component / ~4000-character budget in §4 governs the message *around* it
and nothing inside it. Layout, color, typography and iconography in the
chart are unconstrained — the only real limits are Pillow and the fonts
present on the deploy box.

### 3.2 Palette — vibrant, no colorblind constraint

| Role | Hex | Notes |
|---|---|---|
| Approved | `#4bce7a` | |
| New / open | `#4a90f5` | |
| Denied | `#f0555a` | |
| Blacklisted | `#dd1c1d` | sampled from the supplied flag icon |
| Denied before | `#ffcc00` | sampled from the supplied flag icon |
| Not loyal to WU | `#f17511` | sampled from the supplied flag icon |
| Canvas / card | `#0b1018` / `#111822` | |
| Ink / muted / faint | `#f2f3f5` / `#b5bac1` / `#80848e` | |

Card fills are the accent blended toward the background (`tint()`, 16–18%)
with a 1px accent outline — not flat gray panels.

⚠️ **An earlier version of this file specified a different palette
(`#43a25a` / `#7b83f0` / `#e0656a`) validated with the `dataviz`
colorblind/CVD six-check battery. That is rescinded and must not be
reinstated.** Colorblind safety was never a requirement here — it was
self-imposed during design and explicitly struck: *"I don't like the
colorblind version and we don't have color blind and I never made that
something for you to follow. I just said Non Native English speakers."*
The three flag hexes above are sampled directly from the artwork rather
than chosen, so they match their icons exactly. The only standing
audience requirement is the plain-English copy rule in §8.

### 3.3 Chart layout, as decided

Top to bottom, full width (`1400×740`, 2× supersampled then downscaled):

1. **Header** — hand-drawn bar glyph, `Ticket Console — overview`, and a
   counts subtitle (`8 tickets · Main 3 · FWA 5`). `updated just now` with a
   refresh glyph sits **top-right**. No bot logo or emoji is drawn into the
   chart — the bot's own Discord avatar beside the message is the only
   branding needed, and duplicating it inside the image was rejected.
2. **Three status tiles** — Approved / New-open / Denied, **full width,
   equal thirds**. Tinted fill, accent outline, a circled icon badge in the
   top-right of each tile, oversized count, label beneath.
3. **By clan type** — one row per type. Real Main/FWA badge artwork, the
   type name, a plain-English breakdown line (`1 approved · 1 new/open · 1
   denied`), a segmented bar, and `N total`. **Bars share one scale across
   rows** so Main and FWA are visually comparable rather than each
   self-normalized.
4. **Flags** — directly *underneath* by-clan-type (moved there deliberately),
   as one full-width card of three tinted pills: icon, label, count.
5. **Footer** — one monospace line: `drawn by WU Wizard · attached to the
   message · redrawn when a ticket changes`.

### 3.4 Icons: real PNG assets or hand-drawn shapes — never emoji glyphs

**No Unicode emoji is ever rendered through a font in this chart.** Color
emoji support across Pillow builds and server font setups is unreliable, so
an emoji that looks right locally can render as a box, a mono glyph, or
nothing at all on the Hetzner box. Two sanctioned approaches only:

- **Supplied artwork**, pasted with real alpha (`paste_icon()`, cropped to
  content via `getbbox()` and centered) — five assets, all verified as
  genuine RGBA transparency, not white-matted:

  | Asset | Used for |
  |---|---|
  | `flag_blacklisted.png` | Blacklisted — red slash over WU wings |
  | `flag_denied_before.png` | Denied before — yellow warning triangle |
  | `flag_not_loyal.png` | Not loyal to WU — orange broken heart |
  | `clan_main.png` | Main clan badge |
  | `clan_fwa.png` | FWA clan badge |

- **Hand-drawn PIL primitives** for everything else — plain geometry, no
  font dependency, identical on any box. In use: check, plus and × (the
  three status-tile badges), the refresh arc, and the header bar glyph.

The production renderer and these five production assets are listed in §10;
the similarly named renderer under `docs/ticket-console/` is a standalone
visual reference only.

## 4. Search — three input types, and a hikari correction

**Inputs, and only these three:** Discord ID, player tag, or username.
Nothing else. The bot validates the text after submit:

| Input | Rule | Rejection copy |
|---|---|---|
| Discord ID | 17–20 digits, numeric only | "That is not a Discord ID. A Discord ID has 17 to 20 numbers. Ticket numbers do not work here." |
| Player tag | starts `#`, then 3–9 alphanumerics | "That is not a player tag. A player tag is 3 to 9 letters and numbers after the #." |
| Username | 2–32 chars, `[\w .-]` | falls through to username, no separate error |
| anything else | — | "Use a Discord ID, a player tag (start it with #), or a username. Enter only one of these values." |

Entry points: the `🔍 Find a ticket` button on the console, and a
`/ticket find` slash command reachable from anywhere (not just the channel
the console lives in) — mirrors the original proposal's Archive row (§2.1),
whose entry points are `/ticket history member:@user` and `/ticket find`
(`/ticket console` is the Queue's entry, not the Archive's).

### ⚠️ Correction: Status/Clan-type cannot live inside the modal

The mockup's "Find a ticket" modal shows a text field *and* two select
dropdowns (Status, Clan type) in one submit. **That is not buildable on this
stack.** [`components-v2-in-hikari.md`](components-v2-in-hikari.md) already
established why, for a different feature, and it applies verbatim here:

> `ModalActionRowBuilderComponentsT = TextInputBuilder` — that is the entire
> allowed set, at 2.3.5 *and* at 2.5.0. `LabelComponentBuilder` does not
> exist in any hikari version, and Discord requires selects in modals to be
> Label-wrapped. Multi-axis filtering must therefore use select menus on a
> message (one interaction per axis), with modals reserved for **free-text
> input only**.

Re-checked 2026-08-17 against hikari's current `latest` docs — still no
Label builder. This is not a stale finding.

**Corrected flow:** the modal carries the text field only (now genuinely
optional — a blank submit is "show everything"). Submitting opens the
ephemeral results panel, and Status/Clan-type live there as two ordinary
message string selects (`min_values: 0`, clearable), each re-rendering the
panel in place — the exact mechanism §2.4 already specified for the old
in-console filters, just relocated to the results panel instead of the
shared console or the modal. This keeps every constraint everyone actually
asked for: the shared console stays at three elements (image, picker, Find a
ticket), status/type filtering still exists, and it is real hikari code, not
aspirational Discord-platform code.

Budget check on the results panel, worst case (10 results, the existing cap
from §2.6, unchanged): container 1 + heading Text 1 + 2 filter-select rows
(2 each) 4 + separator 1 + 10 result rows (Section + Text + Button accessory,
3 each) 30 + New-search row 2 + footer Text 1 = **40 of 40.** The original
10-result cap (§2.6: "top 10 with jump links, never a browsable list") must
therefore hold.

## 5. Flags and FWA Chocolate — implemented staff flow

Three flag kinds are staff-authored and match a ticket by Discord ID **or** any
permanently recorded player tag. Either identity match is sufficient, and only
one kind blocks approval:

| Kind | Blocks Approve? | Source |
|---|---|---|
| Blacklisted | **Yes** | FWA ban verified by a recruiter on FWA Chocolate |
| Previously denied | No — caution only | Warriors United ticket history |
| Not loyal to WU | No — caution only | Warriors United recruiter note |

The chart uses the shorter label **Denied before** for the
`Previously denied` count. **Blacklisted**, not “On blacklist,” is the
authoritative blacklist label. Blacklist state is binary, not tiered; the bot
never renders a “maybe” verdict.

### Manage Flags is the primary authoring path

Every ticket detail has **Manage flags**. A recruiter can add a flag, update its
reason, or remove an active flag after recording a permanent removal reason.
The manager binds the latest stored Discord ID and every permanently recorded
player tag; account names are display-only. Flag changes refresh matching open
staff panels and the shared console.

The recruiter-only slash commands remain fallback and audit tools when the
ticket-detail panel is unavailable:

```text
/ticket flags identity:<Discord ID or #player tag>
/ticket flag-add kind:<flag> reason:<reason> discord-ids:<IDs> player-tags:<tags>
/ticket flag-remove flag-id:<exact ID> reason:<reason>
```

### Automatic Chocolate pages use current accounts only

When an FWA ticket opens, its staff thread automatically receives Chocolate
checklist pages containing one review link per **currently linked** account,
grouped safely across multiple messages when needed. A later successful account
refresh updates those pages in place and retires extra pages if the current list
shrinks. Permanently recorded tags that are no longer linked still match search,
history, and flags, but do not stay on the current-account checklist.

A failed lookup and a successful result with zero accounts are different states
in the staff copy. Before the first account result is persisted, the candidate
sees the pending check while staff account and Chocolate panels may be absent.
Recovery creates or updates the staff panels after a result is stored. On a
later failure, the last confirmed current snapshot can remain visible while the
lookup retries. The checklist is staff only; no per-tag `/fwa chocolate`
command is required for the ticket workflow.

Every Chocolate item is only a link to the external review page. A recruiter
must open it, read the site, and use **Manage flags** to record a verified
concern. The bot does not fetch, infer, or save a Chocolate blacklist verdict.

### Newly linked FWA accounts pause approval for review

Approve and deny both force-refresh all linked accounts immediately before the
decision. Approval fails closed if that lookup fails or if it confirms zero
currently linked accounts. It also checks active blacklist flags against the
Discord ID and every permanently recorded tag, including identities discovered
by that final refresh.

If an FWA approval refresh discovers an account that was not in the preceding
current snapshot, the ticket remains open. The bot durably queues and attempts a
staff-context and Chocolate-page refresh, then tells the recruiter to review the
refreshed links and click **Approve** again. If delivery is not yet current, the
second attempt remains blocked while recovery retries it. Any still-new account
found on a later attempt repeats the same gate. This is a human-review gate, not
an automatic Chocolate verdict.

Denial does not use the approval gate: a failed or zero-account final lookup
does not prevent denial. A failed lookup is stored with the decision and retried
automatically so the durable staff context and Chocolate pages can catch up.

## 6. Applicant context and ticket history

The bot delivers an automatic applicant-context panel to the staff thread when
a ticket opens and refreshes it when account identity or matching flags change.
It distinguishes the latest current linked-account snapshot from the append-only
set of permanently observed tags. A failed lookup is never rendered as a
confirmed zero-account result.

When a Discord ID or any observed player tag matches an **earlier** ticket (any
status), that same staff context includes prior-ticket links independently of the
flag system:

> 📜 **This person has opened a ticket before.**
> One earlier ticket matches this Discord ID or player tag.
> [glyph] **FWA #167** · Denied — "Got his butt hurt and left" · 5 months ago
> [Open FWA #167 thread]
>
> The old thread is never deleted. Open it and read before you answer here.

This history is deliberately broader than flags: an unflagged returning
applicant still gets it. Delivery and later refreshes are durable retry work,
including a recovered account snapshot for a ticket already denied. The console
detail also shows matching flags, recorded tags, and earlier tickets whenever a
recruiter opens it.

## 7. Permanence — nothing is ever closed

**Tickets are permanently Approved or Denied. Nothing is ever "closed,"
archived-as-a-status, or removed.** This is the entire reason the migration
to threads exists in the first place — Part 1.1's honest justification
("discoverability and workflow," not capacity) is the same reasoning, just
carried one step further: a ticket you can't find again is as bad as a
ticket you deleted.

Console copy reflects this directly: `❌ Denied · the thread is kept
forever — find it from the console any time`, never "closed."

### Implemented Discord thread lifecycle

Two different concepts must not be called “closed”:

- **Ticket status** — `open` / `approved` / `denied`. This is the one that
  never means “gone.” It lives in Mongo, is what the console renders, and is
  terminal but permanent for approved/denied.
- **Discord's `archived` flag on the thread object** — a dormancy flag, not
  a deletion. The messages and thread ID remain intact.

After approve or deny, the runtime locks and archives both the candidate and
staff threads. If a Discord update fails after the decision is recorded, durable
recovery keeps retrying it. Console jump links open terminal threads read-only;
they remain archived and locked. The runtime does not auto-unarchive them on a
view and has no close or reopen workflow.

## 8. Copy standard

New console, linked-account, Chocolate, flag, and decision guidance is written
for a non-native English speaker: short sentences, common words, no unexplained
jargon, and no new idioms. Some intentionally preserved legacy questionnaire
prompts predate this standard and are not templates for new copy. The FWA
capital gold question is the canonical example of getting new guidance precise
as well as simple: members raid **with their own clan only** and **donate**
Capital Gold to family clans that still need it — they never raid in another
family clan. Any new copy that says "raid the other clans" is wrong and reads as
a rules violation to anyone who takes it literally.

## 9. Implemented boundaries

- Recruiter workflow does not use claim, release, close, or reopen. The shared
  console exposes ticket detail, flags, approve, deny, search, and history.
- The canonical runtime stores only `open`, `approved`, or `denied`; there is no
  `abandoned` runtime state. `closed` is legacy input only and must be explicitly
  classified as approved or denied during store migration.
- One console channel is bound once. Re-running `/ticket console` repairs or
  reuses that hub in its saved channel; it does not relocate it.

## 10. Where the reference artifacts live

The shipped runtime and its visual references are separate:

| Path | What it is |
|---|---|
| `extensions/commands/tickets/console.py` | Shipped console, ticket-detail, Manage Flags, staff-context, and automatic Chocolate flows. |
| `extensions/commands/tickets/console_render.py` | Shipped Pillow chart renderer used by the persistent hub. |
| `docs/ticket-console/render_overview.py` | Standalone visual reference renderer. It is not imported by the runtime. |
| `docs/ticket-console/ticket-console-mockup.html` | Clickable pre-implementation visual reference. It is not runtime authority. |
| `assets/tickets/*.png` | The five icon assets from §3.4, at source resolution with real alpha. Production assets — the renderer loads them at these paths. |

Only the two files under `docs/ticket-console/` are reference artifacts. The
production console imports its shipped renderer and loads the production icon
assets.

The mockup is a browser artifact and is **not** bound by §3.4's
no-emoji rule — that rule is specific to the Pillow-rendered PNG, where
font support is the risk. Emoji in Discord message copy and in the mockup's
own HTML render fine and are used deliberately.

## Related

- [thread-ticketing-proposal.md](thread-ticketing-proposal.md) — the
  research and migration plan this design sits on top of.
- [legacy-ticket-migration.md](legacy-ticket-migration.md) — the separate
  backfill design for cloning old channel-based tickets (this server or
  others being consolidated) into searchable threads.
- [ticket-data-model.md](ticket-data-model.md) / [ticket-status-lifecycle.md](ticket-status-lifecycle.md)
  — the underlying ticket lifecycle references. The implemented flag store is
  durable, audited, and matched at render and approval time by Discord ID or
  recorded player tag.
