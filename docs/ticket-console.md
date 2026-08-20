# Ticket console — decided design

Decided 2026-08-17, in mockup review. **Supersedes Part 2 of
[thread-ticketing-proposal.md](thread-ticketing-proposal.md)** — that file's
Part 1 (research), Part 3 (migration/architecture) and Part 4 (risks) still
stand and are not repeated here. This file is the equivalent of
[todo-dashboard.md](todo-dashboard.md) for `/todo`: the "as decided"
description, not the research trail.

Reference implementation: an interactive, clickable HTML mockup
(`ticket-console-mockup.html`, single self-contained file) was built and
iterated against this exact spec, including full example ticket threads with
real bot panel copy. It is the fastest way to see the actual behavior below;
this file is the fastest way to build it.

**Two corrections against the live codebase are folded in below** — the
mockup briefly got these wrong, and both are the kind of thing that would
have been caught the hard way at build time otherwise. See §4 and §5.

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

**Auto-update, no manual refresh.** The proposal already specified this
(§2.2: "Text: live counts (bot edits this on state change only)") — it just
wasn't built out as a full mechanism. It now is: `create_ticket`,
`store.transition` (approve/deny) each call `refresh_hub()` on their way out
— recount, redraw the PNG, edit the persistent message. A manual "⟳ Refresh"
button was in early mockup drafts and was **removed** once this was made
explicit: there is no state the shared message can be behind on that a click
would fix, so the button had no job. Debounce rapid bursts (e.g. a wave of
approvals) inside `refresh_hub()` itself, not with a user-facing control.
Limitation, unchanged from the original design: this can only ever update
the *persistent* message. Someone's already-open ephemeral panel is a
snapshot and does not live-update — expected, not a bug.

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
  `icon_ban()` and `icon_shield()` are also defined but currently have no
  call sites — they predate the supplied artwork that replaced them, and
  are kept only as a starting point if a fourth flag or status ever needs a
  drawn glyph.

Both the renderer and these five assets ship alongside this doc — see
§10.

## 4. Search — three input types, and a hikari correction

**Inputs, and only these three:** Discord ID, player tag, or username.
Nothing else. Validated client-side before submit:

| Input | Rule | Rejection copy |
|---|---|---|
| Discord ID | 17–20 digits, numeric only | "That is not a Discord ID. A Discord ID has 17 to 20 numbers. Ticket numbers do not work here." |
| Player tag | starts `#`, then 3–9 alphanumerics | "That is not a player tag. A player tag is 3 to 9 letters and numbers after the #." |
| Username | 2–32 chars, `[\w .-]` | falls through to username, no separate error |
| anything else | — | "Use a Discord ID, a player tag (start it with #), or a username. Nothing else works." |

Entry points: the `🔍 Find a ticket` button on the console, and a
`/ticket find` slash command reachable from anywhere (not just the channel
the console lives in) — mirrors the original proposal's Archive row (§2.1),
whose entry points are `/ticket history @user` and `/ticket find`
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
from §2.6, unchanged): container 1 + 2 filter-select rows (2 each) 4 +
separator 1 + 10 result rows (Section + Text + Button accessory, 3 each) 30
+ footer media 1 = **37 of 40.** Tight, which is exactly why the original
10-result cap (§2.6: "top 10 with jump links, never a browsable list") has
to hold — it was already right, for a reason that now matters even more.

## 5. Flags — binary blacklist, two cautions, and a second correction

Three flag kinds, all staff-authored records, matched against a ticket by
Discord ID **or** player tag (either match is sufficient; a ban on any
linked tag bans the whole player record):

| Kind | Blocks Approve? | Source |
|---|---|---|
| Blacklisted | **Yes** | FWA ban, confirmed via FWA Chocolate |
| Denied before | No — caution only | our own past tickets |
| Not loyal to WU | No — caution only | recruiter note |

**The label is "Blacklisted," not "On blacklist"** — renamed everywhere
during review (console copy, chart pill, mockup). Each flag has dedicated
artwork rather than an emoji; see §3.4.

**Binary, not tiered.** There is no "maybe" state. A ban either is or is not
on record for that Discord ID / player tag; the console never renders an
in-between.

### ⚠️ Correction: `/fwa chocolate` doesn't return a verdict — a human does

The mockup's Chocolate Clash panel shows the bot posting a structured
result — "FWA status — ⛔ BANNED — this player is blacklisted" — as if the
bot fetched and parsed that. **It doesn't, and per the existing command it
can't automatically today.** The real command
(`extensions/commands/fwa/chocolate.py`) is `/fwa chocolate player-tag:#TAG`
(or `clan-tag:`), and all it does is post a public link button —
`https://cc.fwafarm.com/cc_n/member.php?tag=...` — with copy that says
*"This will open the FWA Chocolate site to show: … Blacklist status (if
any)."* No parsing happens server-side. This matches an earlier finding in
this same research effort: `cc.fwafarm.com` is login-gated to automated
fetches (the service changed hands in Jan 2025), so a scrape-and-parse
version of this command was never viable, and the shipped command was
deliberately built as a link-out, not a lookup.

**Corrected flow:** recruiter runs `/fwa chocolate player-tag:#TAG` in the
staff thread → bot posts the real link-button message, unchanged → recruiter
clicks through, reads the ban status on the actual site with their own eyes
→ recruiter is the one who then records the finding, which is exactly what
the flag record already models (`addedBy`, `checkedAt`, `source: "FWA
Chocolate · FWA ban list"`, `reason`) — that half of the design was already
right. Only the bot-message copy needs to change: generic link-out, not an
inline verdict.

## 6. Ticket history — fires for everyone with history, not just flagged people

When a Discord ID or player tag matches an **earlier** ticket (any status),
the staff thread gets an automatic panel the first time it's opened,
independent of the flag system entirely:

> 📜 **This person has opened a ticket before.**
> One earlier ticket matches this Discord ID or player tag.
> [glyph] **FWA #167** · Denied — "Got his butt hurt and left" · 5 months ago
> [Open FWA #167 thread]
>
> The old thread is never deleted. Open it and read before you answer here.

This is deliberately broader than the flag system — it is a plain "have we
seen this person" check against every prior ticket by ID/tag match, with a
jump button straight into the old thread. A flagged person also has this
fire; an unflagged returning applicant still gets it. Nothing about it
depends on `FLAGS`.

## 7. Permanence — nothing is ever closed

**Tickets are permanently Approved or Denied. Nothing is ever "closed,"
archived-as-a-status, or removed.** This is the entire reason the migration
to threads exists in the first place — Part 1.1's honest justification
("discoverability and workflow," not capacity) is the same reasoning, just
carried one step further: a ticket you can't find again is as bad as a
ticket you deleted.

Console copy reflects this directly: `❌ Denied · the thread is kept
forever — find it from the console any time`, never "closed."

### Reconciling this with Part 3.3's `archived: true, locked: true` step

Part 3.3 of the proposal has the thread era doing, on close: `archived:
true, locked: true` in one PATCH, with `locked` there specifically to stop a
stray message from silently reopening a resolved ticket. Two different
things were being called "close" and need to be told apart:

- **Ticket status** — `open` / `approved` / `denied`. This is the one that
  must never mean "gone." It lives in Mongo, it's what the console renders,
  and it's terminal-but-permanent for approved/denied, same as today.
- **Discord's `archived` flag on the thread object** — a dormancy flag, not
  a deletion. An archived thread's messages are 100% intact and the thread
  is still reachable by ID; it just needs one unarchive PATCH before a
  jump-link click lands the recruiter inside it, because archived threads
  reject interactions (Part 1.3).

These don't have to be the same decision. **Recommended, not yet confirmed
by you:** keep using Discord's `archived` flag purely as invisible plumbing
against the real, undocumented ~1000-active-thread ceiling (Part 4.1, risk
#8) — auto-archive old resolved tickets in the background, auto-unarchive on
jump-click, and never let either action touch the Mongo `status` field or
any user-facing copy. To a recruiter this is indistinguishable from "never
archived": nothing is deleted, nothing reads as closed, every old ticket is
still one click away. The alternative — literally never archiving anything,
ever — is simpler to reason about but reintroduces risk #8 with no
mitigation once tickets genuinely never leave the active-thread count. **I
went with the plumbing interpretation because it's the only one that
satisfies both "never closed" and "don't silently hit an undocumented
Discord cap" — flag if you meant the stricter, literal version instead.**

## 8. Copy standard

Everything a candidate or a recruiter reads on the console or in a ticket
thread is written for a non-native English speaker: short sentences, common
words, no idioms, no jargon left unexplained. This is not a nice-to-have —
most of the recruiting audience is exactly that. The FWA capital gold
question is the canonical example of getting this precise as well as
simple: members raid **with their own clan only** and **donate** Capital
Gold to family clans that still need it — they never raid in another
family clan. Any copy that says "raid the other clans" is wrong and reads
as a rules violation to anyone who takes it literally.

## 9. Open items — not decided here

- **Backend claiming's scope.** The console no longer surfaces or uses
  `claimed_by`/`claimed_at` anywhere — "we don't care what the recruiter
  claimed" was explicit. What's *not* decided: whether `/ticket claim` /
  `/ticket release` (already live, Part 4.2 decision #4) get deprecated
  entirely, or just stop being rendered. Cheapest correct move is probably
  "stop rendering it, leave the backend alone" — the console change doesn't
  require touching already-shipped code — but that's a call, not a default
  I made for you.
- **The `abandoned` status** (Part 4.2, decision #3, settled 2026-08-02,
  before this review) was never discussed in the console review and isn't
  in the console's `STATUS` map (`open` / `approved` / `denied` only). If
  it's still wanted, it needs a fourth glyph/color in the console and in
  `render_overview.py`'s stat tiles, and it doesn't conflict with §7 —
  "abandoned" would just be another permanent, findable-forever state, same
  as the other three. Flagging because it's a real gap, not resolving it.
- **The legacy `closed` status** (one document, nothing writes it anymore —
  [ticket-status-lifecycle.md](ticket-status-lifecycle.md)) isn't in the
  console's `STATUS` map either. If that one document is ever surfaced by a
  search, the renderer needs a defensive fallback so it doesn't crash on an
  unknown key. Small, but worth catching before it's a bug report.

## 10. Where the reference artifacts live

Stored alongside this doc so the design isn't only prose:

| Path | What it is |
|---|---|
| `docs/ticket-console/render_overview.py` | The chart renderer, standalone and runnable. Pillow only, no Cloudinary, no network. Run it from the repo root (`python3 docs/ticket-console/render_overview.py`) and it writes `ticket_overview.png`. This is the thing `refresh_hub()` folds in at build time; the module-level demo counts get replaced by real ones. |
| `docs/ticket-console/ticket-console-mockup.html` | The clickable mockup — one self-contained file, open it in a browser. Includes full example ticket threads with real bot panel copy, and embeds the rendered chart as a data URI. ~400 KB, mostly that embedded PNG. |
| `assets/tickets/*.png` | The five icon assets from §3.4, at source resolution with real alpha. Production assets — the renderer loads them at these paths. |

The renderer and the mockup are a **reference implementation, not shipped
code** — nothing imports them and no command calls them yet. They're kept
in-repo because the alternative is a design doc describing a chart that no
longer exists anywhere.

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
  — the underlying `tickets` collection. A new flag record (blacklist /
  denied-before / not-loyal) needs its own small collection — kind,
  `discordIds[]`, `playerTags[]`, `source`, `addedBy`, `checkedAt`, `reason`,
  `active` — matched at render time against a ticket's own ID/tag. Not
  designed in [ticket-data-model.md](ticket-data-model.md) yet; this file is
  the first place it's specified.
