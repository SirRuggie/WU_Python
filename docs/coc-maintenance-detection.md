# Detecting Clash of Clans maintenance (coc.py 3.10.0)

Read from the installed wheel of the pinned version (`coc.py==3.10.0`, see
[`../requirements.txt`](../requirements.txt)), not from memory or the online
docs. Line numbers below are that wheel's `coc/` package.

> ## There is no maintenance _flag_. There is only a 503.
>
> Nothing in coc.py — no client property, no `is_in_maintenance()`, no
> `inMaintenance` boolean, no status endpoint — tells you the API is down. The
> **only** signal is that a request raised `coc.Maintenance`, which is the
> library's name for **HTTP 503**. The library's own maintenance poller does
> exactly this: fires a request, catches the exception. There is no cheaper way
> and no advance warning.
>
> The API also never tells you **when maintenance ends**. No `Retry-After` is
> read, no end timestamp is exposed. Anything the bot says about "back in N
> minutes" would be invented.

## The exception

`coc/errors.py:139`

```python
class Maintenance(HTTPException):
    """Thrown when an error status 503 occurs.

    Service is temporarily unavailable because of maintenance.
    """
```

Exported at `coc/__init__.py:57`, so it is `coc.Maintenance`.

Inheritance matters more than anything else in this file:

```
ClashOfClansException
└── HTTPException          .response .status .message .reason
    ├── InvalidArgument    400
    ├── Forbidden          403
    │   └── PrivateWarLog  403 on a war route
    ├── NotFound           404
    ├── Maintenance        503   ← this one
    └── GatewayError       502 / 504 / timeout
```

`Maintenance` **is a** `HTTPException`. See [The bug this started
from](#the-bug-this-started-from) — that inheritance is the whole reason the bot
spent months unable to tell maintenance apart from any other API failure.

### Attributes on the caught exception

| Attribute      | During maintenance                                                                 |
| -------------- | ---------------------------------------------------------------------------------- |
| `exc.status`   | `503`                                                                              |
| `exc.reason`   | `"inMaintenance"` when the body is Supercell's JSON — see the caveat below         |
| `exc.message`  | Supercell's prose, e.g. _"Service is temporarily unavailable due to maintenance."_ |
| `exc.response` | the `aiohttp.ClientResponse`, or `None` if raised from cache                       |
| `str(exc)`     | `"{reason} (status code: 503): {message}"`                                         |

Set in `HTTPException._from_response`, `coc/errors.py:55-79`.

**Do not branch on `exc.reason`.** Branch on `isinstance(exc, coc.Maintenance)`
/ the `except` type. Two reasons:

1. When a 503 arrives with an **HTML** body instead of JSON — which the library
   itself notes happens ("weird case where a 503 will be raised, but html
   returned") — `coc/http.py:385` runs

   ```python
   text = re.compile(r"<[^>]+>").sub(data, "")
   ```

   The arguments are backwards. `re.sub` is `sub(repl, string)`, so this
   substitutes _into the empty string_ using the HTML as the replacement, and
   **always returns `""`**. That empty string becomes `exc.reason`, and
   `exc.message` is `None`. This is an upstream bug in 3.10.0, still there, and
   it means `exc.reason` is empty exactly in the case you would most want text
   from.

2. We do not talk to Supercell directly (see [Which endpoint, and the proxy
   problem](#which-endpoint-and-the-proxy-problem)), so the body is whatever
   the proxy chose to forward.

## Where it is raised

Two places, both `coc/http.py`, both inside `HTTPClient.request` — the single
funnel every client method goes through.

**1. Live response — `coc/http.py:382-388`**

```python
if response.status == 503:
    if isinstance(data, str):
        # weird case where a 503 will be raised, but html returned.
        text = re.compile(r"<[^>]+>").sub(data, "")
        raise Maintenance(response, text)

    raise Maintenance(response, data)
```

Note what is _not_ there: no retry, no backoff. 503 raises immediately. Only
`500/502/504` get the retry loop (`http.py:390-393`, five tries) and only
timeouts become `GatewayError`.

**2. Replayed from coc.py's own response cache — `coc/http.py:317-318`**

```python
elif status_code == 503:
    raise Maintenance(503, data)
```

coc.py caches error responses in its internal FIFO keyed by URL and re-raises
them until the cached entry ages out (`http.py:299-320`). So **a `Maintenance`
can be raised with no network call at all**, and `exc.response` will be `None`
in that case. Practical consequence for any "is it back up yet?" check: a
success may be up to the cached `Cache-Control: max-age` window late. Passing
`lookup_cache=False` on a probe call bypasses it.

## Which endpoint, and the proxy problem

**Any endpoint.** Every one of the ~40 public methods on `coc.Client` documents

```
Raises
-------
Maintenance
    The API is currently in maintenance.
```

(`coc/client.py`, at every method — 527, 586, 684, 780, 877, 939, 1011, …). It
is not a special route; it is the state of the whole API.

The library's own probe, when it wants to answer "is it up", is a single player
fetch — `coc/events.py:880`:

```python
player = await self.get_player("#JY9J2Y99")
```

i.e. `GET {base_url}/players/%23JY9J2Y99`. Cheapest possible call, one object,
no war-log permission needed, and the tag is a real account the library
hardcodes for this purpose.

**Our client now talks directly to Supercell.** `utils/startup.py` sets its
base URL to `https://api.clashofclans.com/v1` and authenticates with
`COC_API_TOKEN` before extensions load. A 503 therefore comes from the
official API path rather than the retired ClashKing proxy:

```python
return coc.Client(..., base_url="https://api.clashofclans.com/v1", ...)
```

A `coc.Maintenance` exception now reflects an HTTP 503 from that official API
path. The user-facing copy says "Clash is in maintenance", which is the
actionable explanation for members.

## The events client we are not using

`coc.EventsClient` has a real maintenance lifecycle. `coc/events.py:874-901`:

```python
async def _maintenance_poller(self):
    maintenance_start = None
    while self.loop.is_running():
        try:
            player = await self.get_player("#JY9J2Y99")
            await asyncio.sleep(player._response_retry + 1)
        except Maintenance:
            if maintenance_start is None:
                self._in_maintenance_event.clear()
                maintenance_start = datetime.now(tz=timezone.utc).replace(tzinfo=None)
                self.dispatch("maintenance_start")
            await asyncio.sleep(15)
        except Exception:
            await asyncio.sleep(DEFAULT_SLEEP)
        else:
            if maintenance_start is not None:
                self._in_maintenance_event.set()
                self.dispatch("maintenance_completion", maintenance_start)
                maintenance_start = None
```

What that gives you, subscribed via `@client.event` + `@coc.ClientEvents.maintenance_start()`
/ `maintenance_completion()` (`coc/events.py:671-673`, `events.pyi:175-177`):

- an edge-triggered callback the moment the first 503 lands,
- a completion callback that is handed the **start** time, so duration is
  computable at the end (never at the start),
- an internal `asyncio.Event`, `_in_maintenance_event`, that the war / clan /
  player pollers `await` on (`events.py:908, 940, 966`) so they idle instead of
  hammering a dead API.

**We do not have any of this.** `utils/startup.py:68` builds a plain
`coc.Client`. Two ways to get it:

1. Switch to `coc.EventsClient` — inherits from `Client`, so every existing call
   keeps working, but it also starts clan/player/war pollers and an
   end-of-season poller as background tasks the moment it is constructed
   (`events.py:449`). That is a real behaviour change to take on for one signal.
2. Re-implement the poller — it is ~15 lines, shown above, and it is the honest
   size of the problem. One `get_player` on a timer, an in-memory
   `MAINTENANCE_SINCE: datetime | None`, flipped by the same edges.

Option 2 is what I would do, and it composes with the next section: the _call
sites_ can also set the flag, for free, whenever they eat a `Maintenance` — so
the flag is usually already true before the poller's next tick.

## The bug this started from

`/todo`, run during the 2026-08-06 break, reported two warnings:

> ⚠️ 4 account(s) could not be checked — war lookup failed
> ⚠️ 36 linked account(s) could not be loaded — these results may be incomplete

Both were maintenance, mislabeled. Every handler in the bot was this shape:

```python
except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as exc:
    print(f"[todo] war lookup failed for {clan_tag}: {type(exc).__name__}")
    result = ("error", None)
```

**That tuple collapses.** `Maintenance` and `GatewayError` are both subclasses
of `HTTPException`, so listing all three is identical to writing
`except coc.HTTPException`. Maintenance was caught, logged by class name, and
flattened into the same generic `("error", None)` as a rate-limit or a stray
500 — so nothing downstream could tell it apart, and the panel blamed the
user's accounts for the game being down. The dedicated `except coc.Maintenance:`
has to sit **above** the `HTTPException` one; Python takes the first matching
clause, so **ordering is the entire mechanism**. See [What was
built](#what-was-built) for where those splits now are.

Still unsplit — a maintenance 503 at these sites surfaces as a bare failure, a
blank field, or a swallowed exception:

| File                                                     | Line                                  | Current behaviour                                                                                                                 |
| -------------------------------------------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| `extensions/commands/clan/list.py`                       | 114                                   | only `coc.NotFound` is caught; a 503 propagates out of the command                                                                |
| `extensions/commands/clan/info_hub/handlers.py`          | 67, 268                               | bare `except:` → clan silently renders with no API data                                                                           |
| `extensions/commands/clan/dashboard/update_clan_info.py` | 223                                   | uncaught                                                                                                                          |
| `extensions/commands/fwa/lazy_cwl.py`                    | 1098, 1585                            | caught by the function's outer `except Exception as e` → user sees `str(e)`, i.e. the raw `"inMaintenance (status code: 503): …"` |
| `extensions/tasks/clan_history_tracker.py`               | 137, 253 (via `_safe_fetch`, line 60) | `except Exception` → returns `None`, tracker records an empty roster                                                              |

That last one is the only entry here that is arguably a **correctness** issue
rather than a cosmetic one, and it is the next thing worth checking: if a
maintenance window makes every clan fetch return `None`, confirm the tracker
treats that as "no data" and not as "everyone left the clan".

## What was built

[`utils/coc_maintenance.py`](../utils/coc_maintenance.py) — an observation log,
not a status check. Nothing polls; the commands are the probe.

```python
note_maintenance()        # from every `except coc.Maintenance:`
note_success()            # after every successful coc call
in_maintenance() -> bool
started_at() -> datetime | None
banner() -> str           # the one user-facing line
```

Three decisions in it that are not obvious:

- **Clearing is grace-gated** (`CLEAR_GRACE_SECONDS = 90`). A success only
  counts as recovery once no 503 has been seen for 90s. Clearing on _any_
  success is wrong: during a live break some calls still succeed from coc.py's
  own FIFO cache (`http.py:299-320`), and which of ~50 calls in a `/todo` run
  lands last is arbitrary — one stale hit would wipe a window fifty live 503s
  had just established.
- **`started_at()` is first-503-_observed_, not the true start.** A break that
  begins while nobody runs a command is only noticed when someone does. The
  copy says "stopped answering" rather than "started", which is true either way.
- **No end time, anywhere.** There is no `ends_at()` because the API has none.
  The banner renders `<t:N:R>` rather than a baked-in "12 minutes ago", because
  `/todo` panels persist and auto-refresh — a literal number would be a lie an
  hour later.

Wired into `/todo` and the FWA points monitor:

| File                                     | Line                | What changed                                                               |
| ---------------------------------------- | ------------------- | -------------------------------------------------------------------------- |
| `utils/todo_data.py`                     | 535                 | player fetch — new `except coc.Maintenance` above the blanket clause       |
| `utils/todo_data.py`                     | 703, 781, 843, 1279 | war / CWL group / CWL war / raid — **split** out of the collapsed tuple    |
| `utils/todo_data.py`                     | 429                 | `_gap_note()` — one banner replaces the per-section counts                 |
| `extensions/commands/todo.py`            | 1123                | `_with_account_failures()` — same banner, deduped                          |
| `extensions/commands/todo.py`            | 847, 869            | the two "Couldn't read" render branches                                    |
| `extensions/commands/todo.py`            | 1226                | the all-dead notice gets a maintenance variant                             |
| `extensions/tasks/fwa_points_monitor.py` | 91                  | split; usually the first thing to notice a break, since it runs on a timer |

`_http_detail()` logs the raw `status=` and `reason=` on every non-maintenance
HTTP failure. What to grep for after the next break:

```bash
sudo journalctl -u wu-bot --since "2 hours ago" --no-pager | grep -iE "maintenance|lookup failed"
```

A `[maintenance]` line means the 503 path worked. A `status=502`/`status=500`
on `lookup failed` lines is a separate upstream or network failure, not evidence
that a proxy rewrote a Supercell response.

Recovery needs no special handling: `TTL_ERROR` is 60s
(`todo_data.py:105`), so one **Check now** clears the cached errors once the API
is back, and the first successful call past the grace clears the flag.

Guarded by [`tests/test_coc_maintenance.py`](../tests/test_coc_maintenance.py).
The one that matters is `test_maintenance_is_not_shadowed_by_httpexception` — if
anyone merges the clauses back into one tuple, the feature is silently dead and
that test is what says so.

Scope was `/todo` only, deliberately. Everything in the _still unsplit_ table
above is untouched, and the flag module is shared, so wiring any of it up later
is a per-site `except` split and nothing more.

## Sources

All read 2026-08-06 from the `coc.py==3.10.0` wheel.

- `coc/errors.py:139` — `Maintenance`
- `coc/errors.py:32-91` — `HTTPException`, and where `.reason` / `.message` come from
- `coc/http.py:382-388` — the live 503 raise, and the backwards `re.sub`
- `coc/http.py:299-320` — cached-error replay, including the cached 503
- `coc/http.py:390-393` — why 502/504 retry and 503 does not
- `coc/events.py:874-901` — the maintenance poller
- `coc/events.py:422-423, 449, 908` — `_in_maintenance_event` and the pollers gated on it
- `coc/events.py:671-673`, `coc/events.pyi:175-177` — the two client events
- `coc/client.py` (every method) — `Maintenance` in the `Raises` block
- `utils/startup.py:140-165` — official client base URL and token authentication

The older proxy verification note above was written before the direct-official
API migration. For current behavior, inspect the official API response in the
runtime network path during a real maintenance window.

## Staff alert and reminder recovery (242)

`extensions.tasks.maintenance_alert` observes existing results every 30 seconds via
`utils.background.run_periodic`; it makes **no Clash API request**. One staff-log
Components V2 alert uses centralized `utils.constants.LOG_CHANNEL_ID`, a red
maintenance container, and fully disabled everyone/user/role mentions. A known
message is edited green after five continuous minutes clear. The duration and
ended timestamp describe observed recovery, never an official/predicted API end.
A new observed 503 during those five minutes cancels the timer while preserving the
first observed start and message; detector 90-second grace and alert 5-minute clear
are separate rules. `window_started_at()` keeps the process-local warning window
stable through shorter detector clears; a full five-minute clear permits a new
window/warning.

`utils.maintenance_alert_store` alone owns the singleton `_id='clash'` in bot-config
`maintenance_alert`, with majority writes and revision CAS. It stores message and
channel IDs, first observed start, state, actual last503 observation, clear timer
and bounded edit claim metadata. The initial **uncertain intent commits before
posting**. Any ambiguous send/interruption is never posted again. If no message ID
was confirmed, automatic edits are impossible; the saved uncertain state is kept
until the observed window closes. Known-ID edits can retry safely. Failures log a
safe-class WARNING without traceback; they do not issue test posts or ping staff.
Restarted healthy defaults do not close a persisted alert: actual post-restart
success and a full five-minute clear observation are required. Re-reading stale
maintenance memory is not a new 503 and cannot cancel another worker's timer or
reopen its closed window.
The detector retains its last actual 503 and first accepted clear observation
across healthy transitions, so a complete flap between alert ticks resets the
hold. The five-minute hold uses the observed clear time, conservatively bounded
by worker startup after restart; the green payload uses the actual observed clear
time, never the later alert tick. A persisted destination that differs from
`LOG_CHANNEL_ID` fails closed: no edit, replacement post or automatic retargeting.

Each message edit first saves a dirty render intent using the existing revision
and edit claim. Only that exact intent revision can acknowledge the edit. A stale
red or green completion that conflicts with the current desired render marks its
retained, configured message dirty again;
subsequent ticks reconcile red for an open window and green for a closed window.
The existing `needs_red_edit` field is this reconciliation flag, including stale
red edits after closure. On authoritative closure, `clear_since` retains the actual
displayed clear observation instead of the completed hold timer, so a restarted
worker can reconstruct the same green payload.

Shaka1164 authorizes closed-window receipts in this same owner and collection.
Before replacing a closed `_id='clash'` singleton, the owner commits its receipt
under `clash:<started_at ISO UTC milliseconds>`. This is the existing first-503
window identity represented as a deterministic key, not a pre-existing literal
`window_id` field. Receipt facts are `message_id`, `channel_id`, `started_at`,
`ended_at`, and the exact `final_render` text. Under Shaka1166, an unknown
`message_id` may be filled once by its original POST's actual known return;
thereafter it is immutable, as are the other receipt facts. Normal reconciliation
changes only receipt `revision` and `state`. No collection, index, migration,
backfill, stored field or pruning is added.

The receipt commits before the singleton replacement CAS. A racing old callback
either changes that singleton revision (forcing a reread and dirty-event transfer)
or finds its already committed receipt. A failed/ambiguous receipt insert leaves
the old singleton intact; retry checks the existing receipt's immutable identity
before any replacement or new-window POST. A transferred singleton dirty flag is
cleared by CAS so ordinary replacement retries cannot reactivate an already
reconciled receipt without a new known dirty event.

Known late RED completions dirty only their own window/message/configured
destination, even when that receipt was already `reconciled`. Ticks edit the stored
GREEN render on that exact old message, then acknowledge the exact receipt
revision as `reconciled`. An acknowledgement cannot erase a later RED invalidation.
Reconciled receipts receive no periodic edits or writes until another known late
dirty event; pending old callbacks are still allowed to reactivate them. A known
late GREEN matching the immutable final render does not dirty it. Unknown-ID
uncertain posts stay `unconfirmed` until an actual known return can be attached;
they are never reposted or guessed.

The sole `post=True` winner retains the exact uncertain document it wrote,
including its window/channel/revision, rather than reading an unrelated current
singleton after the write. Before the external call it rechecks that original
window's eligibility; a closed or replaced intent cannot adopt a new window's
POST authority. A transition after that read still carries the same original
intent through Discord and storage; it never posts on the new window's behalf.

An actual returned message ID is different from an unknown timeout. The owner
fills only None on that original window, with configured destination, original
intent and current revision/state CAS. A return during a no-ID close invalidates
that close's old acknowledgement; a return after closure marks its message dirty
GREEN. After replacement, only its own unconfirmed closed receipt can receive the
known ID. A different already-known ID is never overwritten. A duplicate storage
retry with the same ID does not dirty an already-reconciled receipt again.

If archive insertion copied None just before attachment to the old singleton,
the changed singleton revision defeats replacement. The reread transfers the
durable known ID into that same unconfirmed receipt by the fill-once CAS before
replacement proceeds. This closes the handoff gap without a new collection or
transaction protocol. The running worker retains known pending attachments before
awaiting storage and retries only storage/reconciliation on later ticks, including
accepted-write/error and cancellation cases. It never retries the POST. Those
memory-only retries do not promise recovery after process death.

Growth is about one small receipt per maintenance window. Retention is deferred in
the engineering backlog; this batch never deletes receipts. The controlled
rollover regression ends with message123 GREEN and new message456 RED, exactly one
POST for each, even when the old RED finishes last.
Cancellation/unconfirmed edits leave durable dirty intent and never retry a POST.
Storage cleanup failures preserve the original shutdown cancellation. A running
worker retains failed invalidations in memory and retries them before another
tick can render; a storage outage plus process death cannot guarantee that a
stale completion was durably recorded.
This is eventual reconciliation for observed completions, not conditional Discord
edits: a REST request accepted arbitrarily late after process death cannot report
its completion. Known late callbacks retain their own closed receipt authority
across singleton replacement.
Per Shaka1166, further late-callback/window-replacement limitations must be
reported explicitly; at-most-once POST authority and disabled mentions remain
strict. These fixture guarantees are not evidence of live Discord delivery.

Callback provenance remains internal: `post_intent()` requires a positive integer
revision but does not independently authenticate a fabricated positive revision
against the original winning revision. Window, channel and known-ID ownership
checks and the current-revision CAS still apply. The isolated fabricated-callback
case did not demonstrate an extra POST or a ping. This validation limit is
nonblocking under Shaka1166 and must remain visible in the review evidence.

The existing 60-second reminder scan feeds maintenance/success while reminders are
enabled. Per Shaka1141, when **none are enabled**, the existing 600-second FWA detector
(when configured/enabled) and clan-history direct clan/player reads are fallbacks.
Clan-history hooks reuse only existing requests; their tracking semantics and
cadence stay unchanged. `/todo` observations remain on demand. There is **no
always-on ≤60-second detection guarantee** without enabled reminders. This is an
explicit limitation, not a new poller/cadence/request or a claim based on a current
production reminder count.

War-reminder catch-up and gold non-error status are described in
[war-reminders.md](war-reminders.md#clash-maintenance-242). New status fields are
`maintenance_since` and `war_start` in the existing status document; no schema
migration/backfill or separate reminder-storage owner is introduced.
