# hikari owns logging and warnings, and it takes them at construction

**`hikari.GatewayBot(...)` reconfigures the process's logging AND warning
filters as a side effect of `__init__`.** Not `run()`. Not opt-in.

Verified in hikari 2.3.5, `hikari/internal/ux.py::init_logging()`, called from
`hikari/impl/gateway_bot.py::GatewayBot.__init__` (one call site — `run()` does
not call it again):

```python
warnings.simplefilter("always", DeprecationWarning)
logging.captureWarnings(True)
```

## Why this matters

`warnings.simplefilter()` **prepends**. Its entry lands at the front of
`warnings.filters` and wins over everything installed earlier.

So **every warning filter installed before `bot = hikari.GatewayBot(...)` is
dead on arrival**, however early it runs. Import-time is not early enough,
because "early" is the wrong axis — ordering relative to the constructor is the
only thing that matters.

`main.py` carried this on line 2 from the initial commit:

```python
warnings.filterwarnings("ignore", category=DeprecationWarning)
```

It was deployed. It never worked, for the entire life of the repo. coc.py's
`datetime.utcnow()` DeprecationWarnings — ~200 per `/todo` run, from
`coc/utils.py`'s `get_season_start`, `get_season_end`, `get_clan_games_start`,
`get_clan_games_end` — reached the journal the whole time and buried everything
else.

Two rounds of fixes failed before the cause was found, both of them installing
filters *earlier* rather than *later*.

## The rule

**Install warning filters AFTER the GatewayBot is constructed.** In `main.py`
that is `install_warning_filters()`, called once at import (harmless, covers the
import window) and again immediately after the `bot = hikari.GatewayBot(...)`
block. The second call is the one that does the work.

Keep filters **targeted** — a blanket `DeprecationWarning` ignore also hides our
own, and the next real deprecation would be invisible.

## captureWarnings is a red herring for suppression

`logging.captureWarnings(True)` replaces `warnings.showwarning`, so surviving
warnings arrive in journald wearing log formatting rather than bare on stderr.
That is why they *look* like log lines.

It is **not** why filters fail. `warnings.filters` is consulted *before*
`showwarning` is invoked, so a matching `ignore` filter means the record is
never created. captureWarnings alone could never have defeated a filter — the
ordering did.

It is still useful as a **second, order-independent defence**: a
`logging.Filter` on the `py.warnings` logger catches anything that gets past the
filter list, and does not care who prepended what. `main.py` runs both.

## Diagnosing this class of problem

Print the **head** of `warnings.filters`, not just its length, and print it
after every suspected clobber point:

```python
print([(f[0], getattr(f[2], "__name__", f[2])) for f in warnings.filters[:3]])
```

If entry 0 is not yours, ordering lost. A count alone says nothing — the count
went *up* in the failing case, because hikari's entry had been added.

## Related

- [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md) — why we are on
  2.3.5 and why coc.py is pinned at 3.9.1 (3.9.2 fixes the `utcnow()` calls
  upstream, and taking it would remove the noise at source).
- [todo-dashboard.md](todo-dashboard.md) — the `/todo` command whose log volume
  made this worth chasing.
