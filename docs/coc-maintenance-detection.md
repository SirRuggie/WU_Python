# Detecting Clash of Clans maintenance (coc.py 3.10.0)

Read from the installed wheel of the pinned version (`coc.py==3.10.0`, see
[`../requirements.txt`](../requirements.txt)), not from memory or the online
docs. Line numbers below are that wheel's `coc/` package.

> ## There is no maintenance *flag*. There is only a 503.
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

`Maintenance` **is a** `HTTPException`. See [What we do with it
today](#what-the-bot-does-with-it-today) — that inheritance is why the bot
currently cannot tell maintenance apart from any other API failure.

### Attributes on the caught exception

| Attribute | During maintenance |
|---|---|
| `exc.status` | `503` |
| `exc.reason` | `"inMaintenance"` when the body is Supercell's JSON — see the caveat below |
| `exc.message` | Supercell's prose, e.g. *"Service is temporarily unavailable due to maintenance."* |
| `exc.response` | the `aiohttp.ClientResponse`, or `None` if raised from cache |
| `str(exc)` | `"{reason} (status code: 503): {message}"` |

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
   substitutes *into the empty string* using the HTML as the replacement, and
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

Note what is *not* there: no retry, no backoff. 503 raises immediately. Only
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

**But our `base_url` is not Supercell.** `utils/startup.py:76-82`:

```python
return coc.Client(
    loop=active_loop,
    base_url="https://proxy.clashk.ing/v1",
    ...
)
```

So a 503 means **either** "Supercell is in maintenance" **or** "proxy.clashk.ing
is down / returning 503 of its own". `coc.Maintenance` cannot distinguish them,
and neither can we without a second, independent probe. Whatever the bot says to
users must be true under both readings — "Clash's API isn't answering right
now", not "Supercell is performing maintenance". Getting a direct read on
`api.clashofclans.com` would require our own API key and IP allow-listing, which
we do not have on the bot box; the proxy is the whole point of the pin.

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

Option 2 is what I would do, and it composes with the next section: the *call
sites* can also set the flag, for free, whenever they eat a `Maintenance` — so
the flag is usually already true before the poller's next tick.

## What the bot does with it today

Handled — four sites, all the same shape:

| File | Line |
|---|---|
| `utils/todo_data.py` | 674 (current war), 742 (CWL group), 799 (CWL war), 1229 (raid log) |
| `extensions/tasks/fwa_points_monitor.py` | 90 |

```python
except (coc.Maintenance, coc.GatewayError, coc.HTTPException) as exc:
    print(f"[todo] war lookup failed for {clan_tag}: {type(exc).__name__}")
    result = ("error", None)
```

**That tuple collapses.** `Maintenance` and `GatewayError` are both subclasses
of `HTTPException`, so listing all three is identical to writing
`except coc.HTTPException`. Maintenance is caught, logged by class name, and
then flattened into the same generic `("error", None)` as a rate-limit or a
stray 500. **Nothing downstream can tell maintenance apart.** To act on it, a
dedicated `except coc.Maintenance:` branch has to sit **above** the
`HTTPException` one — Python takes the first matching clause, so ordering is
the whole mechanism.

Not handled at all — a maintenance 503 here surfaces as a bare failure, a blank
field, or a swallowed exception:

| File | Line | Current behaviour |
|---|---|---|
| `extensions/commands/clan/list.py` | 114 | only `coc.NotFound` is caught; a 503 propagates out of the command |
| `extensions/commands/clan/info_hub/handlers.py` | 67, 268 | bare `except:` → clan silently renders with no API data |
| `extensions/commands/clan/dashboard/update_clan_info.py` | 223 | uncaught |
| `extensions/commands/fwa/lazy_cwl.py` | 1098, 1585 | caught by the function's outer `except Exception as e` → user sees `str(e)`, i.e. the raw `"inMaintenance (status code: 503): …"` |
| `utils/todo_data.py` | 510 | `except Exception` per tag → every account becomes an error line |
| `extensions/tasks/clan_history_tracker.py` | 137, 253 (via `_safe_fetch`, line 60) | `except Exception` → returns `None`, tracker records an empty roster |

That last one is the only entry here that is arguably a **correctness** issue
rather than a cosmetic one, and it should be checked before any message work:
if a maintenance window makes every clan fetch return `None`, confirm the
tracker treats that as "no data" and not as "everyone left the clan".

## Minimum viable detection, if we build it

```python
# utils/coc_maintenance.py  (sketch, not committed)
MAINTENANCE_SINCE: datetime | None = None   # None = API believed healthy

def note_maintenance() -> None: ...          # call from every `except coc.Maintenance`
def note_success() -> None: ...              # call after any successful coc call
def maintenance_started_at() -> datetime | None: ...
```

- **Set** it from a real `except coc.Maintenance` at the call sites, so the flag
  costs zero extra requests during normal operation.
- **Clear** it only on a confirmed success, and only from a call that bypassed
  the response cache (`lookup_cache=False`), or the cached 503 at
  `http.py:317` will keep it stuck on after the API is back.
- **Poll** `get_player("#JY9J2Y99")` every 15s *only while the flag is set* —
  same interval the library uses. Do not poll when healthy; the call sites
  already do that job.
- **Never claim an end time.** We have none. "Started 12 minutes ago, still
  down" is defensible; "back at 09:30 UTC" is not.

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
- `utils/startup.py:68-82` — our client: plain `coc.Client`, ClashKing base URL

Live verification against `proxy.clashk.ing` / `api.clashofclans.com` was **not**
possible from this session — outbound HTTPS to both hosts is blocked by the
agent proxy (`CONNECT tunnel failed, 403`). Everything above is read from
library source, which is where the behaviour is decided anyway; the one thing
worth confirming on the box during a real window is what the **proxy's** 503
body looks like, since that is the only part Supercell does not control.
