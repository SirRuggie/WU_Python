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

**Not yet verified:** whether that actually removes the delay; the Raids view
with a live raid weekend — `state == "ongoing"` has never returned True, because
every test has been out of season
where "not ongoing" is also the correct answer. That probe cannot fail
differently from success. It needs a Friday.

Also unverified: whether the H2/H3 type step is visibly distinct on mobile
(nobody has said either way), and coc.py 3.10.0's `coc/raid.py` `max()` crash
fix, which is in the raid path and therefore in the same untested window.

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
