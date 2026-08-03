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

Three fixes shipped on inference before this was found. None of them were the
bug. What found it was instrumentation — printing what the code was actually
doing — after the operator said, in as many words, *stop reasoning about the
call path and make it print what it is doing.* That instruction was correct and
the three preceding fixes were not.

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

| Object | `.state` type in coc.py 3.9.1 | Verified how |
|---|---|---|
| `ClanWar` (war, CWL round) | `WarState` enum | Read of `coc/enums.py` + live instrumentation |
| `RaidLogEntry` | plain `str` | Read of `coc/raid.py` v3.9.1: `self.state: str = data_get("state")` |

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

## Statelessness and the dispatcher

Nothing is written to Mongo. Page comes from the `custom_id`, user identity from
`ctx.user.id` on the interaction. The dispatcher's state lookup therefore always
misses, which is fine and intended — every handler defaults all state.

**One colon per `custom_id`.** The dispatcher splits at the **first** colon and
everything after it is the state key, so `action:{id}:{page}` makes the state key
a composite that misses the lookup. `manage_roles.py:366` does exactly that and
its pagination has never worked. Here the view lives in the action name and the
page in the action_id. See [`component-dispatcher.md`](component-dispatcher.md).

---

## Log noise

coc.py 3.9.1 calls stdlib `datetime.utcnow()` in `coc/utils.py`
(`get_season_start`, `get_season_end`, `get_clan_games_start`,
`get_clan_games_end`). Under Python 3.12 each call emits a `DeprecationWarning`,
and one `/todo` run produced roughly a hundred of them — enough to bury every
other log line. Fixed upstream in coc.py 3.9.2, which `requirements.txt`
explains why we have not taken yet.

`main.py` now installs a **targeted** filter on that specific message, twice:
once before the imports and once after them.

**Unresolved:** `main.py` carried a blanket
`warnings.filterwarnings("ignore", category=DeprecationWarning)` from the initial
commit. It was deployed and the spam reached the journal anyway, so something
defeated it. Nothing in this repo touches `warnings.filters` (grepped repo-wide),
which leaves a dependency calling `simplefilter()`/`resetwarnings()` at import
time as the leading candidate — **not confirmed.** The post-import re-assert
beats that whole class of cause without needing to know which library did it,
and the `[startup] warning filters installed` line prints what survived so the
next boot settles it.

---

## Verified vs inferred

**Verified on the live bot:** all four views render and switch; Raids shows
"no raid weekend right now" with nav intact; Private War Logs lists 17 accounts
split by cause; clan logos render where present; the message is standalone with
no reply header; every custom emoji renders including the animated one; the
refresh button renders beside the timestamp; preparation-phase rows appear for
all three affected accounts after the `_state()` fix.

**Not yet verified:** the freshness stamp actually moving after the prefix fix;
the labelled refresh button reading correctly on a phone; per-clan deadlines
rendering the right number for each clan; the targeted warning filter actually
suppressing the spam; the Raids view with a live raid weekend (`state ==
"ongoing"` has never returned True); the H2/H3 type step being visibly distinct
on mobile; auto-refresh, which is not built.

**Never rendered, therefore never seen:** the pagination ActionRow. `PAGE_SIZE`
is 20 and the largest view so far is Private War Logs at 17, so `pages > 1` has
never been true. It is appended *after* `_nav_block()`, which puts page controls
below the red footer and the refresh button — almost certainly the wrong order.
Left alone rather than fixed blind, since it cannot currently be looked at.

**Inferred, not measured:** the ~4000-character message-wide limit and the
40-component budget (Discord does not document either; corroborated by two
third-party sources). The ~28-character mobile wrap budget is an eyeball from
screenshots, not a measurement.

`[todo-diag]` instrumentation is still present on the raid path, by request,
until a live weekend proves it. Remove it then — and note that stripping it
carelessly once left `if` blocks whose only body was a `_d()` call, i.e. a
`SyntaxError` that would have taken the whole bot down on boot.
