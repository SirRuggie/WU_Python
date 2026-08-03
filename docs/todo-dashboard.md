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
| Clan logos | Mongo `clans` collection, field `logo` | existing client |

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
| Private War Logs | a clan whose war log we cannot read | `🔒` |

**Preparation-phase rows are real work.** You cannot attack yet, but you owe the
attack and the deadline is fixed. Dropping them was half of the "all caught up"
bug.

**Private War Logs is excluded from the landing-view logic** (`VIEW_OPENING_ORDER`)
and from the "still to do elsewhere" hint. Its count is usually the largest
number on the panel and it is *not work* — it is a list of conversations to have
with clan leaders. Landing there would bury the attacks the dashboard exists to
surface.

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

**Refresh is a button, not a select option.** The select lists places you can
GO; refresh is something you DO to where you already are. It cannot share the
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
on a row reads as leftover, `🔄 Refresh` reads as a control. Same two lines on
mobile as the accessory produced, identical on both platforms instead of good on
one and broken on the other.

**No view may ever strand the user without navigation.** Every panel this module
produces, including every error and empty state, carries the nav block. Three
`_notice` paths originally did not, and the only escape was re-running `/todo`.
Nav is centralised in `_nav_block()` so this cannot regress per-path.

---

## The freshness stamp, and the bug that froze it

`-# updated <t:N:R>` is built from **when the data was fetched**, never from
render time. A panel served entirely from cache renders now but shows data from
minutes ago, and the cached case is exactly when staleness matters.
`oldest_fill()` takes the **oldest** live entry, because the panel is only as
fresh as its stalest component.

### The bug

The stamp never moved. Clicking Refresh refetched everything correctly — the
logs showed fresh `currentwar` calls with cache-BYPASS responses — and the clock
still read "3 minutes ago". A working button that looks broken is worse than no
timestamp at all.

**Cause: two prefix lists that had diverged.** The Refresh path dropped
`player:`, `war:`, `cwl:`; `oldest_fill()` read `player:`, `war:`, `cwl:`,
**`raid:`**. Raid entries were never dropped, and out of season their TTL is
`_seconds_until_raid_opens()` — *days*. They survived every Refresh carrying
their original fill time, and `min()` pinned the stamp to whenever the process
first rendered a raid view. On every view, forever.

**Fix:** one tuple, `todo_data.DATA_PREFIXES`, used by both sides.
`drop_render_caches()` owns the Refresh drop; `oldest_fill()` defaults to the
same tuple. Add a cached data prefix there and both sides get it. Do not
re-inline a prefix list at a call site.

`oldest_fill()` also **checks the invariant**: after a drop, nothing live under
those prefixes can predate it. If something does, it prints the surviving keys
by name. The failure mode here is invisible from the panel — button works, data
is fresh, only the clock lies — so it has to announce itself.

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

After this, `send=` is the largest single remaining component.

### What `send=` spans — ONE call, and not the one previously documented

`send=` wraps exactly one statement, `await ctx.respond(components=...)`
(`extensions/commands/todo.py:886-887`, and `870-871` on the notice path). It is
**not** a create-then-edit sequence, and the `todo_sessions` write is outside it
— `print(perf.line())` at `:893` runs before `_record_response` at `:895`, so
neither that write nor its `fetch_initial_response()` is counted in `send=` or in
`total=`.

**Correction to an earlier claim in this repo:** `ctx.respond()` after a defer
was documented as `PATCH /webhooks/{app}/{token}/messages/@original`. **It is
not.** lightbulb 3.0.3's `Context.respond` takes the `else` branch when the
initial response has already been sent, and that branch calls
`self.interaction.execute(...)` — a **followup**, `POST /webhooks/{app}/{token}`.
lightbulb's own source comments that this may be unintentional:

> *"This will automatically cause a response if the initial response was deferred
> previously. I am not sure if this is intentional by discord however…"*

The bucket conclusion survives — both are webhook routes, so the panel is still
off the contended `POST /channels/{id}/messages` bucket. The specific route was
wrong.

Two consequences:

- `respond()` in the deferred case returns a **`hikari.Message`**, not the
  `INITIAL_RESPONSE_IDENTIFIER` sentinel. `_record_response` discards it and
  calls `fetch_initial_response()` instead, which returns the *deferred
  placeholder*, a different message. **So `todo_sessions` rows are keyed to the
  wrong message id.** Real defect, found by reading lightbulb's source for this
  write-up, not yet fixed.
- It serialises behind `Context._response_lock`, an `asyncio.Lock` held for the
  duration of the call. Per-context and uncontended for a single invocation, so
  it explains nothing about the ~2 s.

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

`serialize=` was added to sample the `build()` cost from our side using hikari's
public API (safe to call twice: `ContainerComponentBuilder.build()` is pure —
fresh `JSONObjectBuilder`, `self._components.copy()`, no mutation of `self`,
`impl/special_endpoints.py:2579-2597`). It is **excluded from `total=`**, because
it is a duplicate pass the user would not otherwise pay, and `total=` has to stay
comparable with numbers measured before the field existed.

`send - serialize` is the round trip plus deserialisation. **Those two cannot be
separated without reaching inside hikari's `rest.py`, and that is not worth a
fork of the REST layer.**

**`send=` does not scale with account count.** `render_dashboard` windows rows to
`PAGE_SIZE = 20` (`todo.py:582`), so payload size is bounded by rows on the page
and clans within it, not by the 46 or 65 accounts behind them. `send≈2000ms` on
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

## Auto-refresh phase 1 — rows only

`utils/todo_sessions.py`. **Phase 1 writes bookkeeping rows and does nothing
else: no poller, no scheduler, no message edits.** The point is to get real
documents into Mongo and look at their shape before anything is built on them.

Collection `todo_sessions` in the `settings` database. `_id` is the **message
id**, so one panel is one row, upserted: four `/todo` runs give four rows, forty
Refresh clicks on one panel give one row with `interactions: 40`. That is the
shape a refresher wants — it iterates messages, not events — and dedupe rides on
the primary key, so no unique index is needed and a double write cannot produce
two rows.

Written at two points: after `ctx.respond()` in the command, and inside
`_switch()` for every interaction. The command path needs an extra
`fetch_initial_response()` to get a message id at all — lightbulb 3.0.3's
`Context.respond` returns `constants.INITIAL_RESPONSE_IDENTIFIER`, a sentinel
rather than a Message. That GET is on the webhook route, not
`/channels/{id}/messages`. On an interaction the row is keyed to
`ctx.interaction.message.id` — the panel being edited, not a new message — so it
updates the row written when the panel was sent. `ComponentInteraction.message`
is verified present in hikari 2.3.5
(`hikari/interactions/component_interactions.py`).

`kind` separates a real dashboard from a notice panel ("no linked accounts"),
and `last_trigger` records which control fired. Both exist so phase 2 can decide
things that cannot be decided retroactively if the rows never distinguished them
— e.g. whether to retry a notice, since a link service down at 09:00 is probably
up at 09:05.

`AUTO_REFRESH_ENABLED = False` governs the **poller**, which does not exist.
Rows are written unconditionally, because collecting them is the whole exercise.
Do not read the presence of rows as evidence the feature is on.

### Mongo TTL indexes only understand BSON dates

`expires_at` is a `datetime`, while every other timestamp in the document is a
float epoch. That inconsistency is deliberate and load-bearing: **a TTL index on
a numeric field indexes fine, matches queries fine, and silently never
expires.** The collection grows forever and nothing reports an error.

The TTL is pushed forward on every interaction, so an active panel stays and an
abandoned one ages out with no cleanup task. 24 hours is a starting value, not a
considered one. If phase 2 builds a refresher, the right anchor is probably the
soonest deadline in the panel's data — a panel whose war has ended has nothing
left to refresh.

The index is created lazily, once per process, on first write. Without it rows
are still written and read correctly; they just never self-prune. Every entry
point is non-fatal — this is bookkeeping for a feature that does not exist, and
no failure in it is worth degrading the dashboard for.

## Statelessness, routing and pagination

**Nothing the render path reads comes from Mongo.** Page comes from the
`custom_id`, user identity from `ctx.user.id` on the interaction. The
dispatcher's state lookup therefore always misses, which is fine and intended —
every handler defaults all its parameters. A `/todo` panel sitting in DM history
for a year still works, because there is no state document that could have been
evicted.

(Auto-refresh phase 1 does *write* a bookkeeping row per panel to
`todo_sessions`. Nothing reads it, and the render path must never start
depending on it — that property is the whole point.)

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
label, `▶`) appended only when `pages > 1`. `PAGE_SIZE` is 20 rows.

**That row has never rendered.** The largest view so far is Private War Logs at
17 accounts, so `pages > 1` has never been true. It is also appended *after*
`_nav_block()`, which would put page controls below the red footer and the
Refresh button — almost certainly the wrong order. Left alone rather than fixed
blind, since it cannot currently be looked at.

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
seconds ago" on Refresh**; `grep -c utcnow` returns 0 on coc.py 3.10.0.

**Superseded:** the panel used to be a standalone `create_message` with the
ephemeral ack deleted, specifically to avoid the "X used /todo" header. That put
it on `POST /channels/{id}/messages`, the bucket FWA sync DMs also use, where it
took 4.65 s waits. It is now the interaction response — see
[discord-rate-limit-buckets.md](discord-rate-limit-buckets.md). **The header is
back, deliberately.**

It did not remove the delay. `send≈2000ms` on both a cold and a warm run,
measured — moving off the channel bucket bought roughly 1–2 s of the original
4.65 s, not all of it. The remaining ~2 s on one webhook POST is unexplained and
nothing has been measured about it beyond establishing that it is a single call
that does not scale with account count.

**Fixed and verified** (`3c11233`): `_record_response` used to key rows to
`fetch_initial_response()` — the deferred placeholder — while the panel is a
followup message with a different id.

Closing evidence, `/todo` then Refresh:

```
_id 1533937406334472413  interactions=3  last_trigger=refresh
created_at 1785789582.46  updated_at 1785790183.62
```

**One row, not two.** The command path and the interaction path wrote the same
document, so the id the command recorded is the panel's. The broken case would
have produced a second row with `interactions=1`, because the interaction path
keys off `ctx.interaction.message.id` and always did.

That is the test that discriminates. A query returning only `last_trigger='command'`
rows with `interactions=1` proves nothing — it cannot tell "fixed" from "the
interaction path never ran".

**Auto-refresh phase 1 can now safely read these rows.**

**Not yet verified:** the Raids view with a live raid weekend — `state ==
"ongoing"` has never returned True, because every test has been out of season
where "not ongoing" is also the correct answer. That probe cannot fail
differently from success. It needs a Friday.

Also unverified: whether the H2/H3 type step is visibly distinct on mobile
(nobody has said either way), and coc.py 3.10.0's `coc/raid.py` `max()` crash
fix, which is in the raid path and therefore in the same untested window.

**Inferred, not measured:** the ~4000-character message-wide limit and the
40-component budget (Discord does not document either; corroborated by two
third-party sources). The ~28-character mobile wrap budget is an eyeball from
screenshots, not a measurement.

`[todo-diag]` instrumentation is still present on the raid path, by request,
until a live weekend proves it. Remove it then — and note that stripping it
carelessly once left `if` blocks whose only body was a `_d()` call, i.e. a
`SyntaxError` that would have taken the whole bot down on boot.
