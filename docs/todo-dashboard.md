# `/todo` — the player to-do dashboard

What each of a user's linked Clash accounts still owes. DM-first, Components V2,
stateless. Built 2026-08-02/03.

Files: [`extensions/commands/todo.py`](../extensions/commands/todo.py) (command,
rendering, handlers), [`utils/todo_data.py`](../utils/todo_data.py) (fetching,
cache, view building), [`utils/clash_links.py`](../utils/clash_links.py)
(Discord → tags).

The pre-build research and the layout options are in
[`todo-dashboard-proposal.md`](todo-dashboard-proposal.md). This file is what
the thing actually is.

## Delivery and privacy

`/todo` is persistent in a bot DM and ephemeral in a guild channel:

| Invocation | Visibility | Why |
|---|---|---|
| Bot DM | Persistent DM message | The user can scroll back to the dashboard and use it again |
| Guild channel | Ephemeral | Linked-account activity is visible only to the user who ran the command |

The command always defers first. In a DM it then sends a standalone bot-authored
message and deletes the loading response; in a guild it edits the deferred
ephemeral response. Component clicks edit the existing panel and therefore
preserve its visibility.

If standalone DM delivery raises, the command falls back to the interaction
response so the user still gets a dashboard. That webhook-backed fallback is
labelled manual-only and is not registered for automatic edits: interaction
tokens expire after 15 minutes, so promising a long-lived scheduler there would
be false.

---

## THE BUG THAT COST FOUR FIXES: `str()` on a coc.py enum

**`str()` on a coc.py enum returns the in-game display name, not the value.**

```python
str(WarState.preparation)   # -> "Preparation"   NOT "preparation"
WarState.preparation.value  # -> "preparation"
```

`coc.enums.ExtendedEnum.__str__` returns `in_game_name`. Every comparison of the
form `str(war.state) == "preparation"` is therefore **always False**, silently.
Six sites had it. The dashboard reported "All caught up" to a user with three
pending CWL hits, because every preparation-phase war was classified as
something else and dropped.

**It cost four fixes.** Three shipped on inference and none of them were the
bug. What found it was instrumentation — printing what the code was actually
doing — after the operator said, in as many words, *stop reasoning about the
call path and make it print what it is doing.* That instruction was correct and
the three preceding fixes were not.

The general rule, which this session then broke a second time on the `utcnow`
noise below: **after two failed fixes, stop fixing and start measuring.**

The guard is `_state()` in `todo_data.py`, and **nothing in this feature may
call `str()` on a state directly**:

```python
def _state(obj) -> str:
    raw = getattr(obj, "state", None)
    if raw is None:
        return ""
    return str(getattr(raw, "value", raw))
```

It uses `getattr(raw, "value", raw)` rather than `raw.value` because not every
`state` in this codebase is an enum — see the next section.

### Which states are enums and which are plain strings

| Object | `.state` type | Verified how |
|---|---|---|
| `ClanWar` (war, CWL round) | `WarState` enum | Read of `coc/enums.py` + live instrumentation |
| `RaidLogEntry` | plain `str` | Read of `coc/raid.py`: `self.state: str = data_get("state")` |

Both still hold in coc.py 4.0.0 — `ExtendedEnum.__str__` and `WarState` are
unchanged there, checked directly at the v4.0.0 tag. **This trap does not go
away with a version bump.**

So `_get_raid`'s `str(getattr(entry, "state", "")) != "ongoing"` is correct
**by luck of the type**, not by design. It was written before `_state()` existed.
It is safe today; if coc.py ever converts that field to an enum, the raid view
silently reports "no raid weekend" forever. Route it through `_state()` if you
touch it.

**The raid `== "ongoing"` branch has never been observed returning True.** Every
test so far has been out of season, where "not ongoing" is also the correct
answer — the probe cannot fail differently from the expected result. This is the
same trap as the ClashKing link-API negative (see
[`clashking-discord-links.md`](clashking-discord-links.md)). It needs a Friday.

---

## Data sources

| What | Source | Auth |
|---|---|---|
| Discord ID → player tags | `POST https://api.clashk.ing/discord_links` | none |
| Player, clan, war, CWL, raid log | coc.py via `proxy.clashk.ing` | proxy handles it |
| Recent player → clan candidates | Mongo `player_clan_candidates` | bot-owned, 30-day TTL |
| Clan logos | Mongo `clans` collection, field `logo` | existing client |

### Cross-clan war discovery

The official player endpoint returns one current clan and **no clan history**.
coc.py's `PlayerEvents.joined_clan` / `left_clan` compare consecutive in-memory
polls; they do not retrieve old movement and a restart loses their baseline.
The latest coc.py release does not add a history endpoint. Do not build this
feature around a method that does not exist, and do not rely on ClashKing's
join/leave feed: it was missing the live August 2026 Ansh movements that
triggered this work.

`extensions/tasks/clan_history_tracker.py` builds a bounded local candidate
index instead:

- every 10 minutes it snapshots every registered family clan roster;
- it persists one current-roster snapshot per family clan. Comparing snapshots
  detects who left even across a bot restart; removed clan rows expire after 30
  days instead of accumulating. Stable rosters update that one snapshot and do
  not emit one history write per member on every scan; history changes are
  written only for the initial baseline, joins, and departures;
- when someone leaves a family roster, their tag goes through the bidirectional
  ClashKing link endpoint: departing tag → Discord owner → every linked account
  belonging to that owner. Those accounts are watched for 48 hours and polled
  every 10 minutes regardless of destination clan;
- if that link expansion fails, retry state stays on the same 48-hour watch row.
  Retries back off from 10 minutes to at most 6 hours, process at most 100
  source players per scan, and never extend retention;
- accounts used directly by `/todo` also receive a 48-hour watch. This covers a
  linked user even when none of their accounts was present in a registered
  family roster during the latest expansion;
- active regular-war rosters for registered clans and active CWL rosters for
  clans whose database type is `CWL` are indexed as obligations. This is the
  bootstrap path for a war spun before the tracker existed, including a player
  who has already returned to their home clan;
- actual presence is stored as `last_seen_at`; active roster membership is
  stored separately as `war_until` / `cwl_until`. A CWL roster proves an attack
  obligation but does not pretend to prove the player was physically in that
  clan during the last 48 hours;
- candidate rows expire through the `purge_at` TTL index 30 days after their
  last observation. Player watch rows expire after 48 hours. Current members
  keep one coalesced player/clan row updated; departed combinations age out, so
  movement cannot make either collection grow forever.

At render time `/todo` starts three operations together: current player
lookups, one bulk candidate query for all linked tags, and one bulk watch
upsert. There is no per-account history call and no serial discovery phase.
Current plus candidate clan tags are deduplicated before the existing bounded
war/CWL fan-out.

**A candidate is not proof that the player is in this war.** Both builders must
call `war.get_member(player_tag)` and skip `None` before calculating attacks.
Historically `_used_attacks()` returned zero for both "not rostered" and
"rostered with zero attacks"; using it as the membership test creates false
0/2 rows for every recent clan.

The tracker deliberately does **not** poll every linked alt of every current
family member forever. At 1,000 accounts that would be 144,000 player requests
per day at a 10-minute interval; Mongo space would be tiny, but continuous load
on ClashKing's free proxy would not be neighbourly. Polling is activated by a
real signal—a `/todo` use or a family-roster departure—and expires after 48
hours.

The unavoidable boundary: the API offers no global list of clans and no past
membership lookup. A player who has no Discord link is still watched by their
departing tag, but their alts cannot be expanded. A random-clan hop that began
and ended before this tracker ever observed the player cannot be reconstructed,
and a complete join-and-leave between two 10-minute roster polls can be missed.
Observable family departures are covered prospectively without knowing
destination clans; active registered wars are also covered immediately as a
startup bootstrap.

There is **no `/link` command and no local link table.** The ClashKing endpoint
is bidirectional and unauthenticated — post an array of Discord IDs, get back a
tag→owner map. Details and the response-shape trap in
[`clashking-discord-links.md`](clashking-discord-links.md).

`resolve_tags()` filters by **value, not key**: the response echoes the queried
identifier back as a key with a `null` owner, so keying on presence returns a
bogus `"#505227988229554179"` tag.

`resolve_tags()` returns `None` for *lookup failed* and `[]` for *succeeded,
nobody linked*. Collapsing those told users with a working link to go and link
an account. The same distinction was fixed in `fwa/lazy_cwl.py`'s
`get_discord_ids` for the same reason.

### A ZERO-LINK ACCOUNT CANNOT TELL YOU THE ENDPOINT IS DEAD

**Never probe this endpoint with a Discord ID that has no linked accounts.** It
returns `null`, which is indistinguishable from "the reverse lookup is not
supported" — and that is exactly the wrong conclusion someone drew from it,
confidently, in writing. The same call with an ID that *has* links returns 46
tags. The endpoint was bidirectional the whole time.

Probe with an ID known to be non-empty, or the negative result proves nothing.
This is the general rule in [`../CLAUDE.md`](../CLAUDE.md), and it recurred
during the endpoint survey: `/capital/bulk` and `/war/{tag}/basic` both returned
`{}` and `null` when probed with a **player** tag where a **clan** tag was
required, which reads identically to "endpoint does not work". Both returned
real data on re-probe.

### There is no bulk war route

Confirmed twice against both OpenAPI specs. The war fan-out **cannot** be
collapsed into one request, so call reduction has to come from caching. Full
inventory, including the 401-gated `/ck/bulk` and the 2.1 MB `/capital/bulk`
firehose, in
[`clashking-war-endpoints.md`](clashking-war-endpoints.md).

---

## The four views

Switched by a select menu. Only **actionable** accounts appear — an account with
nothing outstanding is not a row.

| View | A row means | Emoji |
|---|---|---|
| War | an unused attack in a live or preparing war | `War` |
| CWL | an unused attack in the current CWL round | `CWL` |
| Raids | unused Capital Raid attacks this weekend | `RaidMedals` |
| Private War Logs | a current or recent clan whose war log we cannot read | `🔒` |

**Preparation-phase rows are real work.** You cannot attack yet, but you owe the
attack and the deadline is fixed. Dropping them was half of the "all caught up"
bug.

**Private War Logs is excluded from the landing-view logic** (`VIEW_OPENING_ORDER`)
and from the "still to do elsewhere" hint. Its count is usually the largest
number on the panel and it is *not work* — it is a list of conversations to have
with clan leaders. Landing there would bury the attacks the dashboard exists to
surface.

War, CWL, and Private War Logs use the same recent-clan candidates. If a player
was observed in another clan during the 48-hour history window, that clan is
also represented in the diagnostic view; otherwise War could warn about an
unreadable historical clan while Private War Logs incorrectly said every clan
was readable.

If even one linked player profile fails to load, every view is marked
incomplete. An empty partial result says that not every account could be checked
and must never render as **All caught up**. Non-empty partial results keep the
rows that were found and add a warning note.

### Raids: absent ≠ done

A member missing from the raid roster has used **zero** attacks, not all of them.
`entry.get_member(tag)` returning `None` means *has not started*, and the row
must render `0/5`.

The limit is `attack_limit + bonus_attack_limit`, computed **fresh every render**.
`bonus_attack_limit` is earned mid-weekend, so a row can legitimately read 5/5
done, vanish, then reappear as 5/6. ClashKingBot hardcodes `/5` and misses this;
we do not.

The weekend is gated on **the API's own `state`, never the calendar.** Midweek
the endpoint still returns 200 with the previous weekend's entry in state
`ended`; rendering that tells every member they owe six attacks.

### "Couldn't read" must never render as "all caught up"

A failed section renders an explicit *couldn't read this section* panel. "All
caught up" is a verdict on the **whole dashboard** and may only be said when
every view is empty — saying it per-view told a user with three pending CWL hits
that there was nothing to do, because the default view happened to be the empty
one.

Likewise an empty Raids view out of season says *no raid weekend right now*,
not "all caught up" — that would be claiming credit for work that was never
available.

---

## Layout decisions

All of these came from **observed mobile rendering**, not from theory. The
constraint throughout: a phone, a narrow column, ~28 characters before wrap.

**Nothing may wrap.** The first version's clan headers
(`CLAN · prep · opens in 18 hours · closes in 2 days`) wrapped to two lines for
every clan. Timing moved out to a block heading, stated **once per block**
rather than once per clan, because time is what varies and clan is not.

**`<t:N:R>` and `` `backticks` `` render as grey chips, not text.** A chip is
fine at the *end* of a *short* line — `Battle Day · ends in 5 hours` reads as one
sentence. It only shatters a line long enough to wrap. This was over-corrected
once: the timestamp was moved to its own line, which cost two lines for one fact.
It is back inline. **If a block label ever wraps, shorten the label — do not
split the line again.**

Row counts still carry no backticks and **lead** the row, because a chip whose
x-position depends on the name before it destroys vertical alignment.

**Block headings name the game state, not a bare verb.** `Opens` alone said an
event was happening without saying which. The table is `BLOCK_LABELS`, per view:
`Battle Day` / `Prep Day` for war and CWL, `Raid Weekend` for raids.

**A HEADING MAY ONLY ASSERT WHAT IS TRUE OF EVERY ROW BENEATH IT.** The heading
briefly carried the deadline too — `Battle Day · ends in 5 hours` — built from
`min()` across the block. With two clans in the same Prep Day block at 9h29m and
3h51m from battle day, it displayed *starts in 4 hours* over both. A member
reading it for the first clan would have arrived five and a half hours early.
Same defect class as the empty-state bug: a confident number that is wrong for
most of the rows under it, which is worse than no number at all.

The deadline is now a **subtext line under each clan name** — `-# starts in 9
hours`. Not a suffix on the clan name line: `Morning Woods!` plus a chip is
already 28 characters, at the wrap limit before any name grows. A subtext line
cannot collide with the name, and being smaller it reads as a caption on the
clan rather than competing with it.

`min()` *within* one clan is safe — every row there belongs to the same war, so
the stamps are equal. It is only a lie across clans.

**The state-first grouping survived that fix, deliberately.** What defines a
block is the thing that IS uniform across it — can I attack now, or am I waiting
— and that is the most important distinction on the panel. Regrouping by clan
would interleave live and waiting clans and lose it. Only the clock varied, so
only the clock moved.

**Four type sizes, one per level.** `##` panel title, `###` block heading,
`**bold**` clan name, plain row, `-#` subtext hint. The `##` title is a
**deliberate departure from house style**, which is `###` everywhere else in the
repo: flat panels do not need four levels, this one has three under the title,
and at `###` the title was the same size as the clan names so nothing read as
the title.

**The Media footer sits above the freshness row, not at the bottom** — the only
panel in the repo where it is not the last child. The red line reads as the rule
that closes the dashboard, with the timestamp and its refresh button beneath it
as a caption. Done by reordering *inside* the Container: a top-level component
renders outside the accent bar and would lose the coloured stripe.

**Check now is a button, not a select option.** The select lists places you can
GO; checking is something you DO to where you already are. It cannot share the
ActionRow with the select — a row holds **either** up to 5 buttons **or** exactly
one select, never a mix — and it cannot go inside a Section as a select either,
because `SectionBuilderComponentsT` is TextDisplay only.

**A Section accessory button does not stay on one line at mobile width.**
Measured, not theorised: on desktop it rendered `updated 7 minutes ago  [🔄]` as
one row exactly as intended; on a phone the accessory dropped to its own line
and read as stranded — the precise problem the accessory had been chosen to
solve. Mobile is the primary venue, so a desktop-only win loses.

It is now a **labelled button in its own ActionRow** under the freshness text.
Since it wraps to a second line on mobile regardless, it is put there
deliberately, and the label is what stops it looking stranded: a bare icon alone
on a row reads as leftover, `🔄 Check now` reads as a control. Same two lines on
mobile as the accessory produced, identical on both platforms instead of good on
one and broken on the other.

**No view may ever strand the user without navigation.** Every panel this module
produces, including every error and empty state, carries the nav block. Three
`_notice` paths originally did not, and the only escape was re-running `/todo`.
Nav is centralised in `_nav_block()` so this cannot regress per-path.

---

## Check status and freshness

The footer reports **when this panel last completed a check**, not the oldest
entry in the process-wide cache. The old cache-derived timestamp could be pinned
by an unrelated user's raid entry and was therefore not a truthful timestamp for
the panel being read.

An active DM panel renders one compact line:

```text
Checked 2 minutes ago · Rechecks about every 10 min · Stops in 22 hours
```

Both times use Discord timestamps, so they remain localized and advance without
another message edit. `Checked` changes only after the dashboard data was
computed and the Discord message edit succeeded. The stop time is the stored
session deadline, so a panel that has aged out never continues claiming it is
live.

Guild panels are ephemeral and never scheduled. Their footer says
`DM /todo for auto-checks`. Both contexts keep the labelled **Check now**
button.

"Checked" is deliberate wording. The bot may satisfy a lookup from its bounded
cache; "fetched" would incorrectly promise that every source was bypassed. Check
now still drops wu-bot's render caches, while coc.py and the upstream proxy may
legitimately satisfy the resulting request from their own TTL caches.

`oldest_fill()` remains a cache diagnostic, and `DATA_PREFIXES` remains the
single source for manual cache-drop coverage, but neither drives user-facing
freshness text now.

### It happened a second time: `cwlwar:`

Found by auditing every `cache_put` key against `DATA_PREFIXES`, not by anyone
noticing stale rows.

```
"cwlwar:#ABC".startswith("cwl:")  ->  False    # "cwlw" != "cwl:"
"cwlwar:#ABC".startswith("war:")  ->  False
```

Individual CWL round wars are cached under `cwlwar:{war_tag}` for up to **24
hours** on ended rounds. The prefix matched nothing in `DATA_PREFIXES`, so
Refresh never dropped them and `oldest_fill` never aged them.

**The symptom was the inverse of the raid bug.** `raid:` was counted but not
dropped, so the stamp froze *old*. `cwlwar:` was neither, so the stamp
**under-reported** staleness — it could read "updated just now" over CWL data a
day old.

> **CONFIRMED WORKING**, 2026-08-03, on a 34-clan roster with CWL live:
>
> ```
> dropped={'player:': 110, 'war:': 41, 'cwl:': 41, 'cwlwar:': 24,
>          'raid:': 41, 'links:...': 1, 'clanlogos': 1}
> by_label={currentwar:34,leaguegroup:34,leaguewar:24,player:65,raidlog:34}
> ```
>
> **24 `cwlwar:` keys dropped, 24 `leaguewar` calls made.** The self-checking
> identity holds: Refresh drops the round wars and refetches exactly as many.
> Before `40c97ef` the drop count would have been 0 and they would have been
> served from a cache up to 24 hours old.
>
> This is also the payoff for the two instrumentation fields — neither number
> existed before them, and the fix sat unverifiable for days precisely because
> both were being computed and discarded.

### Why it was unobservable, and how that was nearly mistaken for a negative

**`build_cwl_view` has never emitted a diagnostic line.** Only
`drop_render_caches` and `build_raid_view` do — three `_d()` call sites in the
whole module. The CWL and war diagnostics were **deliberately stripped** once
those views were proven; the policy comment is still there at
`utils/todo_data.py:38-42`:

> *"TEMPORARY DIAGNOSTICS for the raid view — remove once verified on a live
> raid weekend. […] The war/CWL diagnostics were removed after those views were
> proven."*

The `cwlwar:` defect was found **months later**, by auditing every `cache_put`
key against `DATA_PREFIXES`, and **nothing was re-instrumented for it.**

So the obvious test — look for a `build_cwl_view` line in the logs — was
searching for output that has never existed at any point in this feature's life.
Absence of that line said nothing about whether `cwlwar:` keys were being
refetched. **Same shape as the zero-link probe**: an input that cannot produce a
positive result proves nothing when it comes back empty. See
[`clashking-discord-links.md`](clashking-discord-links.md).

The two aggregates that *did* exist were both incapable of answering it:
`dropped=106` summed every prefix, and `worst=…ms/leaguewar` surfaced a CWL call
only if it happened to be the single slowest of ~104.

### What now makes it observable

Both fields use data that already existed and was being discarded — no new
measurement, only stopping the discard:

```
[todo-diag] drop_render_caches dropped={'player:': 46, 'war:': 16, 'cwl:': 16,
            'cwlwar:': 21, 'raid:': 16, ...} total=117
[todo-perf] ... by_label={currentwar:16,leaguegroup:16,leaguewar:21,player:46}
```

`cache_drop_prefix` already returned a per-prefix count that `drop_render_caches`
summed away; `note_call` already received a label it discarded unless it was the
worst.

**`cwlwar:` dropped ≈ `leaguewar` calls is a self-checking identity.** The drop
count alone confirms the fix — those keys existing and being dropped is exactly
what was broken. The pair confirms drop *and* repopulate.

A non-zero `cwlwar:` with CWL live closes this. Zero would mean the fix is not
working.

**An uncovered prefix is silent by construction.** It produces no error, no
stale-looking output, and no failed request; it just quietly stops participating
in Refresh. Twice was enough, so `cache_put` now warns at write time:

```
[todo] CACHE KEY NOT COVERED: 'foo:#ABC' matches no prefix in DATA_PREFIXES
or AUX_PREFIXES. Refresh will NOT drop it and the freshness stamp will NOT
age it. Add its prefix to DATA_PREFIXES.
```

### The full cache table

| Prefix | Key | TTL | Dropped by Refresh |
|---|---|---|---|
| `player:` | `player:{tag}` | **10 min** | yes |
| `war:` | `war:{clan_tag}` | 120 s active / 15 min idle | yes |
| `cwl:` | `cwl:{clan_tag}` | 60 min absent / 10 min active | yes |
| `cwlwar:` | `cwlwar:{war_tag}` | 10 min active / **24 h ended** | yes, **since `40c97ef`** |
| `raid:` | `raid:{clan_tag}` | seconds until Friday — *days* | yes |
| `links:` | `links:{discord_id}` | 6 h | yes, via `extra` |
| `clanlogos` | literal | 60 min | yes, via `extra` |

`DATA_PREFIXES` covers the first five. `links:` and `clanlogos` are
per-invocation rather than per-render, so `drop_render_caches()` takes them as
`extra` from the caller; `AUX_PREFIXES` exists only so the guard knows they are
accounted for.

**The clan-level entries are keyed by clan, not by user**, in a process-global
dict. One fetch per clan serves every account in it and every *user* who touches
it. The only per-user cost is `player:` and `links:`.

---

## THE ORIGINAL FAILURE: the 40-component limit, and paging on the wrong unit

**This is what was actually broken for the 34-clan user, and it had never
worked.** The feature was new and he was the first person past the threshold.

```
BadRequestError: 400 (50035) 'Invalid Form Body'
components: - Total number of components cannot exceed 40
    at extensions/commands/todo.py, sent = await ctx.respond(...)
```

**It presented as "spins and never returns".** A 400 leaves no panel and no
visible error — the ephemeral defer just never resolves. Every performance
investigation in this document was chasing a real but *separate* problem. The
fetch completed fine on his failing run; all 34 `build_raid_view` diag lines
were present, and it threw before the perf line printed, which is why his runs
produced no `[todo-perf]` at all.

### The formula

Counting every node, including nested children:

| Part | Components |
|---|---|
| Container + title + separator + `_nav_block` (7) | **10** — `PANEL_FIXED` |
| per block: heading Text | 1 |
| separator between blocks | B − 1 |
| **per clan with a thumbnail**: Section + Text + Thumbnail | **3** |
| per clan without one: a bare Text | 1 |
| separator between clans | C − B |
| notes | +2 |
| pagination row: ActionRow + 3 Buttons | +4 |

**Total ≈ 4C + B + 9**, where **C = distinct clans on the page** and B = blocks.

### The driver is CLANS, not rows

| | C | B | Components | |
|---|---|---|---|---|
| operator | 2 | 2 | 19 | ✅ |
| **threshold** | **7** | 2 | **39** | ✅ |
| | 8 | 2 | 43 | ❌ |
| 34-clan user | up to 20 | 2 | ~91 | ❌ |

The operator's 8 pending hits sit in **2 clans** and were never near the limit.
At 34 clans there is roughly one account per clan, so 20 rows means ~20 clans.

**Rows are nearly free; clans are expensive.** `PAGE_SIZE = 20` capped rows —
the wrong unit — so a page could hold an unbounded number of clans. That was the
defect.

### Worst view

**War, which is the default** — hence failing on the first screen. Raids is one
cheaper (raid rows are all `inWar`, so B=1). CWL is safer only because fewer
clans are in CWL at once. **Private War Logs is safest despite often having the
most rows**, because a private war log is a property of the *clan*, so its rows
cluster into few clans.

### The fix: page on components

`_paginate()` walks rows greedily, closing a page when `_page_cost()` would
exceed `COMPONENT_BUDGET`. **Pages are variable length by design.**

`_split_blocks()` is **the one splitter**, used by the cost model *and* both
renderers. Two copies of that predicate — one to render, one to count — is the
drift shape that produced the `raid:` and `cwlwar:` bugs.

**The budget is 38, not 40**, and it charges for things that are not always
there:

```
COMPONENT_LIMIT       40   Discord's hard cap
COMPONENT_HEADROOM     2   absorbs one more Text added without recomputing
COMPONENT_BUDGET      38
PANEL_FIXED           10   container, title, separator, nav block
RESERVE_NOTES          2   always assumed
RESERVE_PAGINATION     4   always assumed
```

**`RESERVE_PAGINATION` must be unconditional or the logic is circular**: the
pagination row appears only when `pages > 1`, so budgeting for it only once
paginated would push page 1 back over the limit the moment paging began.

That leaves 22 components of content, or **about 5 clans per page** — 34 clans
becomes roughly 5–7 pages. `RESERVE_NOTES` is charged even when a view has no
notes, which costs about half a clan per page; it is a flat reserve for
simplicity and is the obvious tunable if page counts feel high.

`PAGE_SIZE` is **retired**, not renamed — two units in one system is what caused
this.

### Then the pagination row 400'd on its very first render

Fixing the component budget made pagination reachable for the first time, and it
failed immediately:

```
400 (50035) components.0.components.16.components.1.custom_id
 - Component custom id cannot be duplicated
```

**Decoding the path:** `components.0` is the Container, `.components.16` is its
17th child, `.components.1` is that child's second child. Only an ActionRow has
multiple children here — the view select and the Refresh row hold one each, so
child 16 is **the pagination row** and child 1 is its middle "Page N/M" label.

**The clamps were the bug.** The three buttons were:

| Button | custom_id |
|---|---|
| ◀ | `todo_{view}:{max(0, page - 1)}` |
| label | `todo_{view}:{page}` |
| ▶ | `todo_{view}:{min(pages - 1, page + 1)}` |

- **page 0** — `max(0, -1)` is `0`, which *is* `page`. ◀ collides with the label.
- **last page** — `min(pages-1, page+1)` is `page`. ▶ collides with the label.
- **middle pages** — `page-1, page, page+1`, all distinct. Fine.

So it broke on the **first and last** page and worked in between. Since every
paginated panel opens on page 0, it failed on arrival every time — but a
3-or-more-page panel would have worked on page 2, which is exactly the kind of
partial success that makes a bug look intermittent.

**Fix: do not clamp inside the custom_id.** Unclamped they are consecutive
integers and cannot collide. Out-of-range was already handled twice over —
`is_disabled` prevents the click, and `render_dashboard` clamps whatever arrives
(`page = max(0, min(page, pages - 1))`), so even a hand-crafted `todo_war:-1`
lands on page 0. `_switch` parses it with a `ValueError` guard defaulting to 0.

One colon per id is preserved throughout.

### RESOLVED — closing evidence

First successful render ever at the 34-clan scale, 2026-08-03:

```
cold   tags=65 clans=34  calls=183  fetch=7516ms  total=10.82s(to-send)
warm   tags=65 clans=34  calls=0    fetch=3ms     total=2.51s(to-send)
```

No 400. `view:war`, `nav:select` and `refresh` all exercised. The operator's own
2-clan run is unchanged — no pagination row, `total=6.24s(to-send)`, no
regression.

**The original `/todo` failure is resolved.** It was the 40-component limit,
reached because paging capped rows instead of clans, plus a `custom_id`
collision in the pagination row that only became reachable once the first half
was fixed.

Note the shape of the win: **the cold path is still 10.82 s for him** and that is
almost entirely upstream fetch. The performance work reduced it but was never
what was broken.

### "Written but never rendered" is its own risk category

**Two defects in a row were found in code that had never executed** — the
pagination row shipped parked and half-built, unreachable because `PAGE_SIZE=20`
meant `pages > 1` never fired at the operator's scale, and the component budget
was never computed at all.

That is distinct from *written but never tested*. Untested code has at least run
somewhere; **unrendered code has never been near a Python interpreter or a
Discord validator.** Both of these were latent from the day they were written and
surfaced only when a scale change made the branch reachable.

The lesson is the same one the raid view is still waiting on: a branch nobody has
seen render is not evidence of anything. If a feature ships with a branch that
cannot fire at current scale, say so in the report and keep it flagged until
something makes it fire.

---

## THERE ARE TWO CACHE LAYERS, AND `warm=` ONLY REPORTS OURS

This one invalidates a reading of the perf line that looks obvious and is wrong.

**Layer 1 — ours.** `todo_data._cache`, a module-level dict keyed by
`player:` / `war:` / `cwl:` / `cwlwar:` / `raid:`. `warm=` counts it,
`oldest_fill()` ages it, `drop_render_caches()` drops it.

**Layer 2 — coc.py's.** `HTTPClient.request` checks its own FIFO **before
issuing any HTTP request**, keyed on `route.url` (coc.py 3.10.0,
`coc/http.py:299-307`):

```python
if isinstance(cache, FIFO) and (lookup_cache or ...):
    try:
        data = cache[cache_control_key]
        ...
        elif not status_code or 200 <= status_code < 300:
            return data          # <- returns without touching the network
```

`cache_max_size` defaults to **10000** and `lookup_cache` to **True**
(`coc/client.py:224, 231`). `main.py` overrides neither, so it is on. Entries
expire on the upstream `Cache-Control: max-age` — measured at ~60 s on players
and ~95-120 s on `currentwar`.

**`drop_render_caches()` reaches layer 1 only.** It has no handle on coc.py's
FIFO and never did.

### The proof, from one refresh run

```
[todo-diag] drop_render_caches dropped=106 prefixes=('player:', 'war:', 'cwl:',
            'cwlwar:', 'raid:', 'links:...', 'clanlogos')
[todo-perf] path=refresh warm=0/46 clans=16 resolve=253ms fetch=6ms
            (players=2ms views=4ms) calls=104 mean=0ms up=48s total=0.26s
```

`calls=104` is **real** — 104 calls were made at our layer and every one was a
layer-1 miss. They completed in 6 ms because coc.py served them all from layer 2.

The discriminator is `resolve=253ms`. `resolve_tags` is the **only** call on that
run that does not go through coc.py — `utils/clash_links.py:41-43` posts to
`api.clashk.ing/discord_links` with its own `aiohttp` session. `links:` had just
been dropped, so it made a genuine network call and took **253 ms**. Everything
routed through coc.py took ~0.

And it closes exactly: `resolve 253 + fetch 6 + render 0 = 259 ms`, reported as
`total=0.26s`.

### KNOWN BEHAVIOUR: Refresh does not force a network refetch

Inside coc.py's TTL window, Refresh drops layer 1, re-requests everything, and
gets layer 2's copies. The stamp moves, `calls > 0` so the panel says
**"fetched"**, and all of that is true *at our layer* — but no request reached
Supercell and the data is identical to what was already held.

`lookup_cache=False` is accepted per-request and popped from kwargs at
`coc/http.py:295`, so a genuine force is available if we ever want one.

**This is an open decision, not a bug.** Layer 2 is doing exactly what it exists
to do, and bypassing it means more load on a proxy we use for free.

**The cold/warm framing elsewhere in this document is incomplete**: `warm=0/46`
means *our* cache was empty, not that the run hit the network. A `warm=0` run
inside coc.py's TTL window is far cheaper than a genuinely cold one, and the
perf line cannot currently tell them apart. `mean=0ms` alongside a large
`calls=` is the tell.

---

## Measured performance

Two consecutive `/todo` runs, no restart between them (2026-08-03):

```
cold  up=44s   warm=0/46   calls=102  players=2469ms  views=7022ms  send=2018ms  total=12.35s
warm  up=162s  warm=46/46  calls=4    players=0ms                   send=1997ms  total=3.39s
```

**The cache works.** 102 calls collapse to 4; the player phase goes to zero.

`warm=0/46` was never a key bug. The cache is a module-level dict, so it dies
with the process, and the bot had been redeployed between every earlier test.
`cached=104` on the cold run had already ruled out "the cache is never written" —
entries were present, they were just younger than the run. The fix was the
10-minute `TTL_PLAYER` plus the `cwlwar:` coverage fix in `40c97ef`.

**Mongo roster persistence was considered and rejected.** Warm runs are fast
enough that surviving restarts is not worth a new collection and a new failure
path.

### Where the cold path actually goes

`calls=102` at `mean=209ms` with concurrency 8 *looks* like it should take ~2.7 s.
It does not, because **concurrency applies to 46 of those 102 calls and not the
other 56**:

- `extensions/commands/todo.py:790-791` — the player phase, awaited to
  completion.
- `extensions/commands/todo.py:802-809` — the view phase, which starts only
  after it returns. **The two phases are strictly sequential**, separate awaits
  in one coroutine.
- `utils/todo_data.py:444` — the semaphore is a **local, created per call inside
  `fetch_accounts`**. It never leaves that function and is never passed to a
  view builder.
- `utils/todo_data.py:718-719, 777-778, 841-842, 961-962` — the four view
  builders are plain `for clan_tag ... await` loops. **No gather, no semaphore,
  no concurrency of any kind.**

So the cold path is 46 calls at concurrency 8, then 56 calls strictly one at a
time. The view phase is the cold-path cost and always was.

### Fixed — measured before and after

`d502c5a` hoisted the semaphore out of `fetch_accounts` and gave the four view
builders a bounded `asyncio.gather` over their clans. Cold runs, same roster:

```
before  fetch=9491ms  players=2469  views=7022              total=12.35s
after   fetch=3947ms  players=1642  views=2305              total=5.53s
        calls=104 mean=247ms worst=904ms/leaguegroup up=30s
```

**Views 7022 → 2305 ms; cold total 12.35 → 5.53 s.** No retry warnings in the
journal at concurrency 8, so the proxy ceiling is not being reached and 8 stays.

The phases remain sequential — players, then views — and the four builders
remain sequential *relative to each other*, because they share the per-clan
caches: `build_blocked_view` re-reads the `war:` keys `build_war_view` just
filled. Running them concurrently would turn those cache hits back into
duplicate in-flight requests. **The win is inside each builder, not between
them.**

### The cold-path arc, and where it stopped

```
12.35s   starting point
 5.53s   view parallelisation (d502c5a)   fetch=3947ms
 6.16s   same run shape + serialize= instrumentation   fetch=4316ms
```

**5.53 → 6.16 is not a regression.** It is run-to-run variance in upstream
fetch — 3947 ms then, 4316 ms now, on the same code path. Nothing between those
two runs changed the number of calls or their concurrency.

The remaining 6.16 s is **both halves external**:

| Component | Cost | Owner |
|---|---|---|
| `fetch` | 4316 ms | CoC API via the ClashKing proxy |
| `send` | 1055 ms | Discord |

**There is nothing local left to optimise.** The only remaining lever on `fetch`
is `POST /ck/bulk`, which would collapse ~104 calls into one — and it returns
`401 Invalid token`. That needs a credential from the ClashKing operator; see
[clashking-war-endpoints.md](clashking-war-endpoints.md).

### What `send=` spans

On a new DM command, `send=` covers standalone `create_message` delivery (or
the interaction-response fallback). The neutral-to-automatic promotion and
ownership bookkeeping happen after the user-visible send. On component actions,
`_switch` now owns `ctx.respond(edit=True)` and holds the owner lock through it,
so `send=` includes serialisation, rate-bucket waiting, the HTTP request, and
deserialisation. The generic dispatcher performs no second edit because every
todo action is registered with `no_return=True`.

The standalone route is deliberate: a deferred followup still carries the
"used /todo" treatment. Full route and fallback analysis lives in
[`discord-rate-limit-buckets.md`](discord-rate-limit-buckets.md).

### `render=0ms` IS MISLEADING — read this before trusting the perf line

**`render_dashboard` constructs hikari *builder objects* and nothing else.** The
JSON serialisation happens later, inside `ctx.respond()`, at
`hikari/impl/rest.py:1484` and `:1499` (`component.build()`, called from
`_build_message_payload` at `:2141`). `deserialize_message` at `:2166` is in
there too.

So `render=` measures object construction and **`send=` contains the
serialisation, the bucket acquire, the HTTP round trip, and the
deserialisation.** Reading `render=0ms` as "rendering is free" is wrong — the
expensive half of rendering was never in that timer.

### Fixed: `warm=` is scoped to the current user's tags

Observed in the wild: **`warm=65/45` — more warm entries than tags**, which is
impossible for one user.

**Mechanism, confirmed from source.** `live_keys('player:')`
(`utils/todo_data.py`) sums over the **entire process-global `_cache`**:

```python
return sum(
    1 for key, (expires_at, _f, _v) in _cache.items()
    if expires_at > now and key.startswith(prefix)
)
```

The cache is keyed `player:{tag}` — **by clan tag, not by user** — which is
deliberate and is what lets one fetch serve every user. But the denominator is
`len(tags)`, which *is* this user's. So a 65-tag user's entries resident in cache
are counted against a 45-tag user's total.

**Only visible when two users run close together**, which is why it took a second
person on the bot to surface it. It affects the diagnostic line only — the panel,
the cache and the fetch are all correct, and `calls=`/`by_label=` remain accurate.

`live_keys_for("player:", tags)` now builds the current invocation's distinct
cache keys and checks them without calling side-effecting `cache_get`. Unrelated
users and expired entries cannot enter the numerator, duplicates cannot inflate
the denominator, and `warm` cannot exceed the linked-account total.

Two fields are **path-specific**. Component actions have no defer timing here,
but `/todo` now owns their edit while holding the refresh lock and can measure
that send. A missing phase prints `-` rather than looking like a measured zero.

**A phase that was never observed now prints `-`.** Presence in `_phase` is
exactly "was this measured", so any future path-specific phase gets it free.

`total=` carries its span. Command and component paths now print after their
send; an unmeasured send is still reported as `to-render`,
which prints after render. **The two are not comparable and the line now says
so.** The span is derived from whether `send` was observed rather than set by a
caller, so it cannot drift. The command path's *number* is unchanged — the
cold-path arc above remains the baseline.

`serialize=` was added to sample the `build()` cost from our side using hikari's
public API (safe to call twice: `ContainerComponentBuilder.build()` is pure —
fresh `JSONObjectBuilder`, `self._components.copy()`, no mutation of `self`,
`impl/special_endpoints.py:2579-2597`). It is **excluded from `total=`**, because
it is a duplicate pass the user would not otherwise pay, and `total=` has to stay
comparable with numbers measured before the field existed.

`send - serialize` is the round trip plus deserialisation. Those two cannot be
separated without reaching inside hikari's `rest.py`, and that is not worth a
fork of the REST layer.

### CLOSED: `send=` is network-bound. Stop investigating it.

```
render=0ms serialize=0ms send=1055ms
```

**`component.build()` is free.** Serialisation is eliminated as a cause, and
deserialising one message is not going to be the other second. Rate limiting was
already eliminated separately: the journal held 20 rate-limit lines total, all
between 2026-07-30 and 2026-08-03 02:15, none on the webhook route and none
during any measured run — so the bucket acquire at `rest.py:804` and the retry
sleeps in the `_request` loop are both ruled out.

That leaves **raw network latency to Discord**, which is not ours to fix. `send=`
has now cost four turns of investigation and the answer is that there was never
anything local in it.

**`send=` does not scale with account count.** `render_dashboard` greedily
windows rows by the nested Discord component budget, so payload size is bounded
by components and clans on the page, not by the 46 or 65 accounts behind them. `send≈2000ms` on
both a 102-call cold run and a 4-call warm run is consistent with that: it is
latency on one webhook POST, independent of everything else measured.

---

## Emoji slots

Custom emoji live in `utils/emoji.py`. The view emoji are used in **both** the
view header and the matching nav select option, so what you pick is what you
land on.

| Attribute | Used for |
|---|---|
| `War`, `CWL`, `RaidMedals` | view headers + nav options |
| `sword_fighting` (animated) | the live/battle block heading |
| `Waiting` | the preparation block heading |
| `refresh` | the refresh button |
| `TH2`–`TH18` | per-row town hall, replacing the text "TH17" |

Unicode, chosen for meaning: `⏰` urgent (pairs with the red accent under 2h),
`✨` caught up (positive without being a checkmark — "done" ≠ "nothing to do"),
`🔒` private war log, `⚠️` lookup failed, deliberately unlike the padlock.

Access is via `_emoji(name)` / `_partial(name)`, which return `""` /
`hikari.UNDEFINED` for a missing or malformed slot. `EmojiType.partial_emoji`
**raises** on a bad ID, and an unrenderable emoji must never take the panel down.

---

## DM automatic refresh

`utils/todo_sessions.py` stores one owner row per user and DM channel in the
`settings` database. `_id` is `dm:{user_id}:{channel_id}`; `message_id` is the
latest panel and `generation` rejects delayed work from a replaced panel. Guild
panels remain ephemeral, manual, and unstored.

New `/todo` and **Check now** start an exact 30-day window. Ordinary navigation
and automatic checks update the checked time and next run but never extend the
deadline. A newer `/todo` replaces the previous automatic panel; the older
message becomes a small manual panel whose Check now button can make it current
again.

The poll loop wakes every minute and selects at most 100 due rows. Each panel is
scheduled ten minutes after its previous successful check, with four concurrent
refreshes maximum. The due query has an `active,next_refresh_at` index. One user
can therefore contribute at most one regular automatic edit; a full 30-day
window is 4,320 checks. A deleted or inaccessible Discord message removes its
exact generation; transient errors postpone only that generation.

Rows written by `7ca8a33` used the numeric message ID as `_id` and promised a
24–72-hour window. The scheduler continues honoring those rows until their
original deadline, so deploying this owner model cannot silently break a
visible promise. A new `/todo` or Check now demotes and removes them; otherwise
the existing TTL bounds their lifetime and storage.

Automatic work does not force the process-wide cache clear used by **Check
now**. It revalidates only an old cached `no war`, ended regular war, or `not in
CWL` answer for the current and recent candidate clans. Positive active wars,
private logs, player and raid data, and unrelated clans remain cached. A
per-clan lock makes overlapping panels share the recheck instead of duplicating
API calls.

Replacement is deliberately ordered: send the candidate with a neutral footer,
change every promised predecessor to manual, compare-and-swap the owner row,
then promote the candidate. A predecessor edit failure aborts replacement and
leaves it scheduled. A Mongo failure leaves the candidate manual. A candidate
promotion failure leaves a scheduled but conservatively manual owner that the
next automatic cycle repairs. No failure ordering leaves an unscheduled message
promising automatic updates.

Todo component handlers own their Discord response (`no_return=True`) and hold
the same weak owner lock as the scheduler through the actual edit. This closes
the interval where the generic dispatcher previously edited after `_switch`
released control. Scheduler reads, marks, postpones, and removals also match
`message_id + generation`, so work loaded before a takeover cannot touch its
replacement.

The production topology is one `GatewayBot` process under one systemd unit, so
the weak locks cover every Discord edit. They are intentionally process-local;
running overlapping bot replicas would require a distributed edit lease before
that topology is supported.

If standalone delivery fails, the command uses the deferred webhook response
and keeps it manual. Check now still performs a manual update there but never
enrolls that short-lived webhook message for bot-token scheduling.

### Mongo TTL indexes only understand BSON dates

`expires_at` is a `datetime`, while every other timestamp in the document is a
float epoch. That inconsistency is deliberate and load-bearing: **a TTL index on
a numeric field indexes fine, matches queries fine, and silently never
expires.** The collection grows forever and nothing reports an error.

The TTL date is the same bounded refresh deadline for DM sessions. Background
checks update `next_refresh_at` and `last_checked_at` but deliberately do not
push the TTL.

The index is created lazily on first write. A failed attempt is retried at most
once per hour; before that retry succeeds, rows are still written and read
correctly but do not self-prune. Every entry point is non-fatal — this is
bookkeeping for a non-critical convenience, and no failure in it is worth
degrading the dashboard for.

## Statelessness, routing and pagination

**Component routing state does not come from Mongo.** Page comes from the
`custom_id`, user identity from `ctx.user.id` on the interaction. The
dispatcher's state lookup therefore always misses, which is fine and intended —
every handler defaults all its parameters. Rendered data may use Mongo-backed
clan history and logos, but an old panel's controls do not depend on an evictable
component-state document.

(The background scheduler reads `todo_sessions`; component rendering does not.
That separation is what keeps an expired or year-old panel's controls usable.)

### ONE COLON PER `custom_id`

The dispatcher splits at the **first** colon and everything after it is the
state key, so `action:{id}:{page}` makes the state key a composite that misses
the lookup. `manage_roles.py:366` does exactly that and **its pagination has
never worked.** See [`component-dispatcher.md`](component-dispatcher.md).

So the view goes in the **action name** and the page in the **action_id**:

| custom_id | Handler | Meaning |
|---|---|---|
| `todo_war:{page}` | `todo_war` | War view, page N |
| `todo_cwl:{page}` | `todo_cwl` | CWL view, page N |
| `todo_raid:{page}` | `todo_raid` | Raids view, page N |
| `todo_private:{page}` | `todo_private` | Private War Logs, page N |
| `todo_nav:{current_view}` | `todo_nav` | select-menu routing |
| `todo_refresh:{view}\|0` | `todo_refresh` | forced refetch of `view` |

Note the `|` separator in `todo_refresh` — a second colon would break the split,
so where a handler needs two values they are packed with a pipe and parsed with
`action_id.split("|")[-1]`.

### How the select menu routes the four views

One `TextSelectMenu` in an ActionRow, built by `_nav_select()`, carrying an
option per view with its emoji and live count. Its `custom_id` is
`todo_nav:{current_view}` — the view you are leaving, not the one you picked.
**The destination arrives in `ctx.interaction.values[0]`, not in the
`custom_id`.**

That is why `todo_nav` is registered **without** `group=`: the dispatcher would
otherwise try to resolve the selected value as an action name. Reading
`values[0]` in the handler is what lets an option carry `"refresh"` as well as a
view name.

`todo_nav` then dispatches to `_switch(ctx, choice, "0", ...)` — always resetting
to page 0, because a page 3 that exists in Private War Logs may not exist in War.

**A retired option must keep working.** Refresh moved out of the select and
became a button, but panels already sitting in DM history still carry a select
with a `"refresh"` option and will fire it forever. `todo_nav` still handles it.
You cannot reach back and edit those messages, so old values are permanent API.
Unknown values fall back to War rather than erroring.

Pagination is a separate three-button ActionRow (`◀`, a disabled `Page N/M`
label, `▶`) emitted only when `pages > 1`. Pages are variable-length and are
bounded by nested component cost rather than a row count. The row sits between
the view selector and footer. Each view, including Private War Logs, has a
registered page handler; Refresh preserves all four views.

---

## The `utcnow` saga: five attempts, and the mechanism was never established

coc.py 3.9.1 called stdlib `datetime.utcnow()` in `coc/utils.py`
(`get_season_start`, `get_season_end`, `get_clan_games_start`,
`get_clan_games_end`). Under Python 3.12 each call emits a `DeprecationWarning`,
and one `/todo` run produced ~200 of them — enough to bury every other log line,
including the `[todo-diag]` output being used to debug the dashboard.

Five attempts. **Four were warning filters and all four failed.** Measured each
time with `journalctl -u wu-bot | grep -c utcnow`:

| # | Attempt | Result |
|---|---|---|
| 1 | blanket `filterwarnings("ignore", DeprecationWarning)`, present since the initial commit | never worked, for the life of the repo |
| 2 | targeted filter on the message, installed at import | 204 |
| 3 | same, re-installed after all imports | 204 |
| 4 | installed after `GatewayBot(...)`, plus a `logging.Filter` on `py.warnings` | 251 |
| 5 | **coc.py 3.10.0** — deletes the `utcnow()` calls | **0** |

### THE FILTERS MAY STILL NOT WORK

**The upgrade sidestepped the question; it did not answer it.** We never
established where the record originated — `warnings` module to stderr,
`warnings` via `logging.captureWarnings` to the `py.warnings` logger, or a
direct `logger.warning()` call in which case `warnings.filters` was never
relevant at all. Those three need completely different fixes and four were
shipped without knowing which.

The decisive one-line diagnostic — read the raw journal line and see whether it
carries a logger name, and which — **was never run.** Do not assume a warning
filter in this process works. There is no evidence any ever has. Full record in
[hikari-logging-and-warnings.md](hikari-logging-and-warnings.md).

Attempts 2–4 were each shipped on a fresh theory after the previous one failed,
which is the same failure mode as the `str(enum)` bug above and was called out
the same way. **After two failed fixes, stop fixing and start measuring.**

### There is no coc.py 3.9.2

Attempts 2–5 all cited "3.9.2" as the release that replaced `utcnow()` with
`now()`. **It does not exist and never has.** PyPI has 3.9.0, 3.9.1, 3.10.0,
4.0.0. The fabricated version number reached `requirements.txt` as a multi-line
justification comment and two docs files before it was checked.

The real fix is 3.10.0, PR
[#273](https://github.com/mathsman5133/coc.py/pull/273) — one PR carrying both
the `utcnow` removal and the non-JSON-response fix that had been split across
the imaginary release.

**Check PyPI before citing a version number.** One command, and it would have
prevented three turns of work built on a version that was never published:

```bash
curl -s https://pypi.org/pypi/<package>/json | grep -o '"version":"[^"]*"' | head -1
```

The same rule already exists in
[`../CLAUDE.md`](../CLAUDE.md) for API surfaces — *an in-repo call site is not
proof an API exists.* A remembered version number is not proof a release exists
either.

---

## Verified vs inferred

**Verified on the live bot:** all four views render and switch; Raids shows
"no raid weekend right now" with nav intact; Private War Logs lists 17 accounts
split by cause; clan logos render where present; every custom emoji renders
including the animated one;
preparation-phase rows appear for all three affected accounts after the
`_state()` fix; per-clan deadlines match the game exactly (9h29m and 3h51m
shown separately, where one `min()` had shown "4 hours" for both); the labelled
refresh button reads correctly on mobile; **the freshness stamp moves to "a few
seconds ago" on Check now**; `grep -c utcnow` returns 0 on coc.py 3.10.0.

**Changed, not yet live-verified:** DM panels again use standalone
`create_message` followed by deletion of the deferred interaction placeholder.
This is now required by the product decision to remove the "X used /todo"
response treatment and by the long-lived automatic editor. Guild panels still
edit the deferred ephemeral response.

### CLOSED: followup messages DO carry the interaction header

This was left open — the hope was that a followup would give the standalone look
on the quiet webhook route, and it was explicitly not asserted without evidence.

**Evidence: direct observation of the live panel.** The current path already
*is* a followup — `ctx.respond()` after a defer takes lightbulb's else-branch to
`self.interaction.execute()`, which is `POST /webhooks/{app}/{token}` — and the
"X used /todo" header is visible on it.

The route choice remains binary:

| Option | Header | Route |
|---|---|---|
| interaction response / followup | **yes** | webhook — uncontended |
| standalone `create_message` | no | `POST /channels/{id}/messages` — throttled at 4.65 s |

The standalone route previously experienced a measured 4.65-second bucket wait,
so `_deliver_panel` keeps a correctness fallback: if channel-message delivery
raises, it edits the already-deferred interaction response. Rate-limit waiting
inside hikari may still make the standalone send slower without raising; the
interaction was acknowledged first, so that delay does not violate Discord's
three-second response deadline.

**Historical fix** (`3c11233`): `_record_response` once keyed rows to the
deferred placeholder instead of the displayed message.

Closing evidence, `/todo` then Refresh:

```
_id 1533937406334472413  interactions=3  last_trigger=refresh
created_at 1785789582.46  updated_at 1785790183.62
```

The current model no longer keys ownership by message. One deterministic row,
`_id = dm:{user_id}:{channel_id}`, carries `message_id` and `generation`. Live
verification must confirm that a second `/todo` changes that row's message and
generation, turns the prior Discord panel manual, and that a delayed automatic
cycle cannot edit or delete the replacement.

**Not yet verified:** the Raids view with a live raid weekend — `state ==
"ongoing"` has never returned True, because every test has been out of season
where "not ongoing" is also the correct answer. That probe cannot fail
differently from success. It needs a Friday.

Also unverified: whether the H2/H3 type step is visibly distinct on mobile
(nobody has said either way), and coc.py 3.10.0's `coc/raid.py` `max()` crash
fix, which is in the raid path and therefore in the same untested window.

**CONFIRMED, was inferred: the 40-component limit, and that it counts nested
children.** Discord stated it verbatim:

```
hikari.errors.BadRequestError: Bad Request 400: (50035) 'Invalid Form Body'
components:
 - Total number of components cannot exceed 40
```

The payload has **exactly one top-level component** — `_panel()` returns
`[Container(...)]` — so a top-level-only count could never exceed 1. The 400 is
the oracle for both facts.

**Still inferred, not measured:** the ~4000-character message-wide limit
(components bound first, so it has never been reached). The ~28-character mobile
wrap budget is an eyeball from screenshots, not a measurement.

**The character limit may be the next wall — but component paging makes it
LESS likely to bite, not more.** Text volume scales with the same thing
components do: each clan contributes a name, a subtext deadline and its rows. A
page bounded at ~5 clans carries roughly 20 rows of text, on the order of 1200
characters — comfortably clear of ~4000. The variable-length pages are variable
in the direction that helps, because the constraint that shortens them is
correlated with the one that would have lengthened the text. **It has still
never been measured**, and the way it would surface is another 400 naming
`content` or a length rather than `components`.

`[todo-diag]` instrumentation is still present on the raid path, by request,
until a live weekend proves it. Remove it then — and note that stripping it
carelessly once left `if` blocks whose only body was a `_d()` call, i.e. a
`SyntaxError` that would have taken the whole bot down on boot.
