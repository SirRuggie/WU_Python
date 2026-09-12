# `/lazycwl` — the Lazy CWL dashboard

Save an FWA clan's roster during CWL, remind whoever hasn't returned home for
a sync war, and turn that reminder into a recurring schedule — all from one
Administrator-only panel. Built 2026-09-12, replacing the nine separate
`/fwa lazycwl-*` slash commands.

Files: [`extensions/commands/lazycwl_dashboard.py`](../extensions/commands/lazycwl_dashboard.py)
(command, S0-S6 rendering, every component handler),
[`extensions/commands/fwa/lazy_cwl_service.py`](../extensions/commands/fwa/lazy_cwl_service.py)
(scheduler lifecycle, the daily expiry cron, reminder sends, the five
orchestration calls the dashboard makes),
[`utils/lazy_cwl_store.py`](../utils/lazy_cwl_store.py) (the only module that
touches the `lazy_cwl_lists` collection),
[`extensions/commands/fwa/lazy_cwl.py`](../extensions/commands/fwa/lazy_cwl.py)
(the nine old command names, now redirect aliases).

The design proposal and every build decision are in `DECISIONS.md` D003,
D009-D020 in `.claude/scratch/lazycwl-dashboard/` — this file is what the
thing actually is, not the reasoning that got it there.

## Entry and the admin gate — TWO layers, not one

`/lazycwl` (`lazycwl_dashboard.py:1414` `class LazyCwl`) is a top-level
Administrator-only slash command: `default_member_permissions=
hikari.Permissions.ADMINISTRATOR` hides it from Discord's command picker for
non-admins, and `LazyCwl.invoke` (`:1427`) additionally checks
`is_admin(ctx.member)` at runtime — the same double layer `/lazyprep` uses,
because the Discord-side permission alone is a UI hint, not enforcement.

`is_admin(member)` (`lazycwl_dashboard.py:69-74`) is the single predicate:
`bool(member and member.permissions & hikari.Permissions.ADMINISTRATOR)`.
Both `/lazycwl` and every `/fwa lazycwl-*` redirect alias call it —
`extensions/commands/fwa/lazy_cwl.py:_redirect` imports it lazily (see
"Redirect aliases" below) so there is exactly one copy of the rule instead of
two that could drift (refuter-15 NOTED 5, closed by this doc's own brief).

**Button and select handlers are protected only by the ephemeral panel
itself, not by a second permission check.** `@register_action` dispatch
(`extensions/components.py`) does not re-run `is_admin` before calling
`handle_save`, `handle_finish_yes`, etc. — every click on a `/lazycwl` or
`/fwa lazycwl-*` panel is trusted because the panel was sent ephemeral to the
admin who opened it and nobody else can see or click its components
(refuter-12, carried over from the original audit). If a panel URL or its
components were ever leaked to a non-admin, they could act through it; this
is a recorded, accepted risk, not a gap someone forgot to close.

## The wording table — the house rule for every new string

Old vocabulary, and the words that replace it everywhere in this feature
(design-01-main.md §2, `tests/lazycwl_wording.py`'s `BANNED_WORDS`/
`ALLOWED_CWL_STRINGS`):

| Old | New |
|---|---|
| snapshot | Saved player list ("Save list") |
| ping | Reminder ("Remind now") |
| auto-pings | Auto reminders ("On"/"Off") |
| roster | Player list |
| reset | Finish (clear list) |
| interval / cadence | How often |
| FWA sync | "war in your home clan" |
| CWL | "league war" |
| TH | Town Hall |

Max 12 words per sentence, one idea per line, emoji only as state markers.
`tests/lazycwl_wording.py` holds the one copy of the banned-word list;
`tests/test_lazycwl_dashboard.py` and `tests/test_lazy_cwl_aliases.py` both
import it (D020 item 5) rather than each carrying a drifting copy. The scan
walks render-facing keyword arguments (`content=`/`label=`/`placeholder=`/
`description=`) and every `rows.append(...)`/`*_row`/`*_line` string
literal (D013 cleanup item 4) — not the module's own docstrings or the
Mongo query value `"FWA"`, which are not user-facing text.

## Screens S0-S6

Every screen is a `Container` built by a pure `render_*` function fed by an
async `build_*` loader; the loader does I/O, the renderer does not, so every
layout is directly testable with fake data. Every custom_id carries **ONE
colon** — action name before it, action_id after — per the repo's stateless
routing rule (`extensions/commands/todo.py`'s rule, restated at
`lazycwl_dashboard.py:12-16`).

| Screen | Action name(s) | action_id encoding |
|---|---|---|
| S0 Home | `lazycwl_pick` (select), `lazycwl_home` (Refresh/Back), `lazycwl_save`, `lazycwl_remind`, `lazycwl_auto`, `lazycwl_players`, `lazycwl_add`, `lazycwl_finish` | `{tag}` — `NONE` (nothing picked), `ALL`, or the clan's own `#TAG` (`_encode_tag`/`_decode_tag`, `:77-89`) |
| S1 Save list result | `lazycwl_save` | same `{tag\|ALL}` |
| S2 Remind now result | `lazycwl_remind` | same `{tag\|ALL}` |
| S3 Auto reminders | `lazycwl_auto`, `lazycwl_auto_every` (select), `lazycwl_auto_on`, `lazycwl_auto_off` | `lazycwl_auto`/`lazycwl_auto_every`/`lazycwl_auto_off`: `{tag\|ALL}`. `lazycwl_auto_on`: `"{tag}-{m}"` via `_encode_auto_on`/`_decode_auto_on` (`:573-590`), decoded with `str.rpartition("-")` — safe because a normalized clan tag never contains `-` |
| S4 Player list / Remove | `lazycwl_players`, `lazycwl_remove`, `lazycwl_remove_pick` (select), `lazycwl_remove_yes` | `lazycwl_players`/`lazycwl_remove`/`lazycwl_remove_pick`: `"{tag}-{page}"` (0-indexed) via `_encode_players_page`/`_decode_players_page` (`:847-857`). `lazycwl_remove_yes`: `"{tag}-{page}-{t1}.{t2}..."` via `_encode_remove_yes`/`_decode_remove_yes` (`:1104-1112`), each `ti` the chosen player's tag with `#` stripped |
| S5 Add player | `lazycwl_add` (opens a modal), `lazycwl_add_submit` (modal submit) | `lazycwl_add`: `{tag}`. Modal custom_id is `"lazycwl_add_submit:{tag}"` |
| S6 Finish | `lazycwl_finish`, `lazycwl_finish_yes` | `{tag\|ALL}` |

**Per-page remove cap and the 100-char reason.** `REMOVE_MAX_PICK = 8`
(`:844`) is a ceiling, not the actual cap: `_remove_pick_cap` (`:986-1006`)
computes, per page, the largest N ≤ 8 such that the N *longest* tags on that
page still keep `lazycwl_remove_yes:{tag}-{page}-{t1.t2...}` under Discord's
100-char custom_id limit (`REMOVE_CUSTOM_ID_BUDGET = 100`, `:843`) — a fixed
8 measured 111 chars for a 10-char clan tag and 8 realistic 9-char player
tags, already over budget. The computed N is what `render_remove_pick` uses
as the select's `max_values`; at realistic FWA tag lengths it lands at 6, not
8.

## The 40-component ceiling, and why home shows one card vs. a compact table

Discord rejects a message over 40 total components, nested children
included. One full clan card (name, player count, away count, reminder
state, expiry — up to 5 `Text` nodes) at every clan costs 18 + 5 per clan:
**43 components at 5 clans, already over the ceiling at today's family size**
(refuter-06 measured it; refuter-16 re-measured 18 + 5·n). D010/D011's fix: with
**exactly one** clan selected, render that clan's full card (`_full_card`).
With **ALL or nothing** selected, render every clan (and every orphan list —
a saved list whose `clan_tag` no longer matches any `mongo.clans` doc) as
**one row each inside a single `Text` component** (`_build_compact_text`,
`_rows_union`), so the compact view's component count never grows with clan
count — only its character count does, capped under
`COMPACT_TEXT_BUDGET = 3800` chars (`:66`) with a "… and {k} more" truncation
when it would not fit. Measured with real hikari builders: one-clan-selected
tops out at 24 components at 40 clans; ALL/nothing tops out at 20. Both stay
comfortably under 40.

## Data model

`utils/lazy_cwl_store.py` is **the only module allowed to touch the
`lazy_cwl_lists` collection** (docstring, `:1-9`); a repo-wide grep test in
`tests/test_lazy_cwl_service.py:874-891` enforces it and fails if the hit set
is ever empty (a zero-output grep passing vacuously was D008's own bug,
fixed there). Document shape (design-01-main.md §9, `save_list`,
`utils/lazy_cwl_store.py:121-163`):

```
_id            ObjectId
clan_tag       str, "#" + upper (utils/lazy_cwl_store.py:_normalize_tag)
clan_name      str
status         "active" | "finished" | "expired"
saved_at       datetime (UTC)
saved_by       int (Discord user id)
expires_at     datetime (UTC) — see "Expiry" below
purge_at       datetime = expires_at + 90 days
finished_at    datetime | absent
players: [{
    tag            str, "#" + upper
    name           str
    town_hall      int
    discord_id     int | None
    added_manually bool
    added_at       datetime (UTC)
}]
reminders: {
    enabled        bool
    every_minutes  int | None
    started_at     datetime | None
    last_sent_at   datetime | None
    sent_count     int
}
```

Three indexes, all owned and installed by `ensure_indexes`
(`utils/lazy_cwl_store.py:100-118`, called from the service's `reconcile()`
at startup — see below): a **partial unique index** on `clan_tag` where
`status == "active"` (one active list per clan), a **TTL index** on
`purge_at` with `expireAfterSeconds=0` (Mongo deletes the document itself),
and a compound `(status, expires_at)` index for the daily expiry scan.

**No migration.** The old `lazy_cwl_snapshots` collection is untouched and
still sits in Mongo — `utils/mongo.py` no longer declares an attribute for
it (D019), but the data itself is not dropped until a later, separate
removal task. `lazy_cwl_lists` (`utils/mongo.py:56`) is the only collection
this feature reads or writes.

## Expiry

`expires_at_for(saved_at)` (`utils/lazy_cwl_store.py:86-97`): 00:00 UTC on
the 16th of the month the list was saved in, or the 16th of the *next*
month if saved on or after the 16th. The daily expiry job
(`EXPIRY_JOB_ID = "lazycwl_expiry"`, `lazy_cwl_service.py:48,197-203`) is a
`CronTrigger(hour=0, minute=10, timezone="UTC")` job registered inside
`reconcile()` — which also runs once at startup, before jobs are restored,
so an already-expired list never gets its reminder job resurrected. The job
(`expire_due_and_stop_jobs` → `store.expire_due`) only flips `status` to
`"expired"` and removes the clan's reminder job; it never deletes a
document — that is Mongo's TTL index's job, 90 days later, via `purge_at`.

## Reminders

Turning reminders on writes `reminders.enabled=True`, resets `started_at`/
`last_sent_at`/`sent_count`, and schedules an `IntervalTrigger(minutes=
every_minutes)` job (`set_reminders`, `lazy_cwl_service.py:408-438`).
`reminder_job` (`:441-474`) re-reads the document by `_id` on every run — a
stale in-memory copy never drives a send — and self-stops once seven days
have passed since `reminders.started_at` (`_reminder_expired`, `:101-109`,
`SEVEN_DAYS = timedelta(days=7)`), posting "Auto reminders for {clan} stopped
after 7 days." to the ping channel. `restore_reminder_jobs` (`:477-506`)
rebuilds every enabled-and-not-expired list's job after a restart, using
`calculate_next_run` (`:112-134`) to preserve cadence rather than replay
missed intervals. **The ping channel is hard-coded**, unchanged from the
retired feature: `PING_CHANNEL = 1424256751913668770` (`:41`).

## Manual add

S5's modal submits a player tag; `add_player_by_tag` (`lazy_cwl_service.py:
347-405`) validates the tag (`coc.utils.is_valid_tag`), looks the player up
(`coc_client.get_player`), and resolves a Discord link via
`get_discord_ids` (`:59-83`) — moved into this module from the old
`lazy_cwl.py` at D019, still owning the **None-vs-{} contract**: `None`
means the link lookup itself failed (do not persist a false "not linked"),
`{}` means it succeeded and nobody is linked. **If the link service is
down, the player is still added** — `reason: "link_service_down"` is
returned so S5 can say so, but the add itself is not blocked on an
unrelated dependency. The result dict's `away_now` key (not a stored player
field) says whether the player is currently in the clan roster, so S5 can
show 🚪 or 🏠. Away status is never persisted; every reminder recomputes it
from the live roster, so a manually-added player who isn't home yet gets
reminders like everyone else.

## The store is the only collection accessor

Repeated because it is the rule most likely to regress silently: nothing
outside `utils/lazy_cwl_store.py` may reference `lazy_cwl_lists` directly.
`tests/test_lazy_cwl_service.py:874-891` runs `grep -rl lazy_cwl_lists
--include=*.py .` and asserts the hit set is non-empty *and* contains only
`utils/lazy_cwl_store.py`, `utils/mongo.py` (which must keep the collection
attribute at `utils/mongo.py:56` — the store's `_coll` returns
`mongo.lazy_cwl_lists`, so deleting that line breaks every store call), and
test files that construct fake collections named after it. A change that
adds a second real accessor fails this test.

## Redirect aliases

The nine old `/fwa lazycwl-*` command names stay registered
(`extensions/commands/fwa/lazy_cwl.py`) so muscle memory and old channel
pins keep working. Each is a thin `SlashCommand` whose `invoke` calls the
shared `_redirect(ctx, mongo)` (`:30-43`): same `is_admin` check as
`/lazycwl`, defer ephemeral, then edit with
`build_home(mongo, selected_tag=None, note=MOVED_NOTICE)` —
`MOVED_NOTICE = "ℹ️ This moved to \`/lazycwl\`. Use it from now on."`
(`:16`), rendered as an extra line under the title by `render_home`'s
existing `note` parameter; no dashboard-side change was needed to support
it. `build_home` and `is_admin` are imported **lazily inside `_redirect`**,
not at module load — a module-level import completed a real circular
import (`lazycwl_dashboard` → `lazy_cwl_service` → `fwa/__init__.py` →
`lazy_cwl`, refuter-14 MUST-FIX 1) and is guarded by
`tests/test_lazy_cwl_aliases.py::test_importing_dashboard_first_does_not_
break_lazy_cwl` / `test_importing_lazy_cwl_first_still_works`, each a fresh
subprocess import.

**Plan to remove:** these nine aliases are deliberately temporary (D002,
D018) — kept only until a refuter or the operator verifies `/lazycwl` in
production. Removing them is a separate, later task; this doc does not
authorize it.

## Test files and the runner

`tests/test_lazy_cwl_store.py` (store), `tests/test_lazy_cwl_service.py`
(scheduler/orchestration), `tests/test_lazycwl_dashboard.py` (every screen
and handler), `tests/test_lazy_cwl_aliases.py` (the nine redirects, the
circular-import guard, the admin gate). `tests/lazycwl_wording.py` holds
`BANNED_WORDS`/`ALLOWED_CWL_STRINGS` and is not itself a test module (its
name does not match `test_*`). Runner: `.venv/bin/python -m pytest -q`.

## RECORDED, NOT FIXED

Left open deliberately — non-blocking, each already reviewed and accepted
rather than missed:

- `extensions/commands/fwa/lazy_cwl.py:35-41` — the `build_home is None`
  lazy-import branch (the only branch production ever takes) had zero test
  coverage until this brief closed it
  (`tests/test_lazy_cwl_aliases.py::test_redirect_end_to_end_through_the_
  real_build_home`); the equivalent branch in `_redirect`'s `is_admin`
  lazy-import is still only covered indirectly through that same test, not
  by a dedicated mutation-proof case (refuter-15 NOTED 1, partially closed).
- `lazycwl_dashboard.py:282-288` — orphan select options (a saved list whose
  clan has no matching `mongo.clans` doc) are appended only into whatever
  select slots remain after up to 24 real clans; at 24+ real FWA clans an
  orphan list has no select option and therefore no reachable Finish button,
  though it still appears as a compact-table row (refuter-07).
- `lazycwl_dashboard.py:199-211` — `_disabled_states` for `ALL` only
  iterates `clans`, so an orphan-only list does not count toward
  `any_has_list`; Remind/Auto/Finish read as disabled under `ALL` even
  though the orphan list itself is still reachable by selecting it directly
  (refuter-07).
- `lazycwl_dashboard.py:393-417`, `:420-442`, `:152-177` — three independent
  "join with `, `/`\n`, truncate with `… and {k} more`" implementations
  (`_cap_names`, `_chunk_rows`, `_build_compact_text`) exist instead of one
  shared helper; all three are test-guarded today, but a fourth copy or a
  divergent fix to one is a real drift risk (refuter-13).
- `lazycwl_dashboard.py:393-417` `_cap_names` always keeps the *first* name
  in a list regardless of budget; a single clan name longer than ~3789
  chars would still render an over-budget line. Unreachable — CoC clan
  names are game-capped at 15 characters (refuter-13).
- `extensions/commands/fwa/lazy_cwl_service.py:275-282` vs `:393-395` — the
  "is this player currently in the clan" predicate
  (`member.tag.upper() not in current`) is written twice, once in
  `away_players` and once inline in `add_player_by_tag`; one rule, two
  copies (refuter-05).
- `extensions/commands/fwa/lazy_cwl_service.py:109` — the 7-day reminder
  cutoff uses `>`, not `>=`; the boundary case (exactly 7 days elapsed) has
  no test (refuter-05).
- Several service-layer result-dict keys have no dedicated test proving
  they are populated on every code path (e.g. `add_player_by_tag`'s
  `not_found`/`already_listed` reasons, `remind_now`'s `total_count` on the
  sent path) — dropping the key still leaves the touched-file suite green
  (refuter-05, reports/refuter-05.md for the full list).

None of the above were in this brief's scope to fix (item (c)/(e) closed
only the two items named there); they are recorded so nobody re-discovers
them from scratch.
