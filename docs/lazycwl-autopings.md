# LazyCWL auto-pings, and the select-all pattern

`/fwa lazycwl-autopings-start` and `-stop`, in
[`extensions/commands/fwa/lazy_cwl.py`](../extensions/commands/fwa/lazy_cwl.py)
(~105 KB, the largest command file in the repo).

## Shape

**Start is TWO steps, stop is ONE.** That asymmetry is the main thing to know
before touching either.

| | Command | Handler(s) |
|---|---|---|
| start | lists snapshots `active:True` **and** auto-ping not enabled | `lazycwl_autopings_select_snapshot` → `lazycwl_autopings_select_interval` |
| stop | lists snapshots with auto-ping enabled | `lazycwl_autopings_stop_select` |

## The scheduler has NO jobstore

`AsyncIOScheduler(timezone="UTC")` is created on `StartedEvent` and shut down on
`StoppingEvent`. Jobs coalesce missed executions, allow one instance, and have a
five-minute misfire window.

**No `jobstores=` argument anywhere — it is the default in-memory store, so
every job dies with the process.** Persistence is entirely Mongo fields on
`lazy_cwl_snapshots`: `auto_ping_enabled`, `auto_ping_started_at`,
`auto_ping_interval_minutes`, `auto_ping_job_id`, `last_auto_ping_at`,
`auto_ping_count`.

`restore_autopings()` rebuilds only `active: true`, `auto_ping_enabled: true`
jobs. Its next run is calculated from `last_auto_ping_at`, falling back to
`auto_ping_started_at`. Missed intervals are skipped rather than replayed, so a
reboot does not restart the cadence or produce a backlog burst. Anything past
its seven-day window is disabled first. That is the `[LazyCWL AutoPing] Active
auto-ping jobs restored` line.

**Consequence:** "the scheduler job is missing" is an ordinary state after any
restart, not an error. Both stop paths treat a missing job as success.

Startup also repairs legacy inactive rows whose auto-ping flag remained enabled
and resolves duplicate active snapshots deterministically. Mongo then enforces
one active snapshot per normalized clan tag with a partial unique index.

## RECORDED, NOT FIXED: `auto_ping_job_id` is written and never read

It is set when a job is created and **read nowhere.** Stop reconstructs
`f"autopings_{snapshot_id}"` independently instead.

**Two sources of truth for one string** — the same drift shape that produced the
`raid:` and `cwlwar:` cache-prefix bugs in `/todo`. They agree today. Nothing
enforces that they keep agreeing.

## RECORDED, NOT FIXED: the 25-option limit is unguarded in four places

Discord caps a select menu at 25 options. **Nothing in this file truncates** —
`grep` for any slice or length check across all option-building blocks returns
nothing.

Four menus now carry an ALL option, which costs one slot and drops the ceiling
to **24 clans**: `lazycwl-snapshot`, `lazycwl-ping`, `lazycwl-reset`, and both
auto-ping commands.

**Clear at current scale** — 7 active snapshots plus ALL is 8 options. If the
alliance grows past ~24 active snapshots this becomes a real defect **in four
places at once**, and it will present as Discord rejecting the interaction
rather than as a truncated list.

## RECORDED, NOT FIXED: `lazycwl_confirm_reset` is dead

`@register_action("lazycwl_confirm_reset")` is registered and **no code emits
that custom_id.** The reset ALL branch executes directly with no confirmation.

## The ping channel is HARDCODED — `announcement_id` is not used

```python
# Hardcoded ping channel for all FWA LazyCWL pings
announcement_channel = 1424256751913668770
```

Every LazyCWL ping for every clan goes to that one channel. `clan_data` does
carry an `announcement_id`, and `fwa/war_plans.py` and
`recruit/dashboard/server_walkthrough.py` do use it — **the LazyCWL ping path
does not.**

Two things follow:

1. **A per-clan `announcement_id` check before creating jobs would be
   meaningless.** It gates on a field that has no bearing on whether the ping
   lands, and would report false failures for clans whose pings work fine.
2. **All auto-pings share one channel bucket.** `POST /channels/{id}/messages`
   is bucketed per channel, so N clans firing together contend with each other
   rather than spreading across N buckets. See
   [discord-rate-limit-buckets.md](discord-rate-limit-buckets.md).

That second point is why bulk start staggers.

## Select-all pattern — follow it, do not invent a variant

Established at three pre-existing sites and now two more. **A `SelectOption`
with `value="ALL"` prepended to the menu, 🌍 label, count in the description,
`max_values` stays 1.** Handlers branch on `if selection == "ALL":`.

### Partial failure

Collect one result dict per item — `{'success', 'clan_name', 'clan_tag',
'error'}` — apply to **every** item regardless of individual failures, then
render counts plus **a named line per failure**. Never a bare count.

`_bulk_autoping_summary()` renders both start-all and stop-all from one
function, so the two cannot drift into reporting failures differently.

### Partial failures and scheduler rollback

The start eligibility query returns only snapshots **without** auto-ping, so
re-running naturally targets whatever failed. Successful clans are not rolled
back because another clan failed. However, if one clan's APScheduler job cannot
be registered after Mongo was updated, that clan's `auto_ping_enabled` flag is
rolled back immediately; the database must not advertise a job that does not
exist. Stop is idempotent — a missing job is not a failure.

### Jitter on bulk start

`next_run_time=now + timedelta(seconds=i*5)`. Without it, N jobs created in the
same second fire together forever after, into the single hardcoded channel
above.

## Confirmation

**ALL gets a confirm step; the per-clan path does not.** Start-all eventually
posts to the ping channel on a repeating interval for every clan; stop-all
silently kills every job and leaves a panel that looks identical to one where
nothing was running.

Pattern copied from `lazycwl_remove_player_confirm` in the same file: DANGER
button + SECONDARY Cancel, both carrying a fresh `button_store` action id, state
on the action doc.

## Which commands should NOT get select-all

| Command | Why not |
|---|---|
| `lazycwl-remove-player` | destructive — bulk-applying a player removal across clans is almost certainly not what anyone means |
| `lazycwl-roster` | read-only, but N rosters in one ephemeral would blow the 40-component / ~4000-char budget |
| `lazycwl-status`, `lazycwl-autopings-status` | already family-wide, no selection to bulk |

## Verification status

Automated on 2026-08-04:

- cadence preservation and missed-interval skipping
- start-time fallback before a first ping
- restore of active/enabled rows only
- inactive/duplicate snapshot repair and unique-index shape
- scheduler registration options and clean shutdown
- stale flag clearing on reset/inactive snapshots
- ping counts increment only when a Discord message is actually sent
- scheduler-registration failure rolls Mongo back to disabled

The full repository suite passed 137 tests. These tests use fakes; creation of
the partial unique index against the live remote Mongo and a real reboot with an
active ping remain unverified from the local workspace.

### Earlier smoke test (historical)

Smoke tested 2026-08-03, `/fwa lazycwl-autopings-start`, **cancelled at the
confirm screen**.

**VERIFIED — the path up to the write:**

- the 🌍 ALL option renders on the start menu
- selecting it advances to the interval step
- the confirm screen renders
- **no exceptions anywhere in the handler chain** — the journal was silent
  throughout

That last point clears the specific failure mode flagged at build time:
`interval_minutes` does reach the confirm handler through the `button_store`
doc, which was the one piece copied from `lazycwl_remove_player_confirm`
without being executed.

**NOT VERIFIED — everything from the write onward:**

- the bulk write itself
- the summary rendering all 7 clans
- the jitter (`next_run_time` staggering)
- restore-on-boot picking up 7 bulk-created jobs
- **the entire stop-all path**, end to end

**A CANCEL-AT-CONFIRM TEST CANNOT DISTINGUISH A CORRECT BULK WRITE FROM A
BROKEN ONE.** It exercises only the path *up to* the write and proves nothing
about what the write does. Do not read the green smoke test as covering the
feature.

Deferred because a real run starts repeating pings into the shared LazyCWL
channel for every clan, which is not something to trigger for a test. The
natural window is the next time auto-ping is genuinely wanted for the whole
family.

## Never use byte-level tools on this file

An in-place `perl` round-trip that read raw bytes and wrote with an encoding
layer **double-encoded every non-ASCII character in the file — 97 lines** of
emoji and `•` separators turned to mojibake in one command. It was caught by
grepping for `Ã`/`â` and reverted with `git checkout`.

Use the editing tools, which preserve encoding. If a bulk edit ever seems
necessary here, verify afterwards with:

```bash
grep -c 'Ã\|â' extensions/commands/fwa/lazy_cwl.py    # must be 0
```
