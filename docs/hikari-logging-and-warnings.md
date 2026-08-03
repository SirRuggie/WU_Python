# hikari owns logging and warnings — and warning filters here have never worked

Two separate facts. The first is established. **The second is not, and that is
the important one.**

---

## UNRESOLVED: warning filters in this process do not work, and nobody knows why

`main.py` carried this from the initial commit:

```python
warnings.filterwarnings("ignore", category=DeprecationWarning)
```

It was deployed. It **never worked**. coc.py's `datetime.utcnow()`
DeprecationWarnings — ~200 per `/todo` run — reached the journal for the entire
life of the repo.

Three further attempts also failed, each measured by
`journalctl -u wu-bot | grep -c utcnow` after a deploy:

| Attempt | What it did | Result |
|---|---|---|
| 1 | targeted `filterwarnings` on the message, installed at import | 204 lines |
| 2 | same, installed again after all imports | 204 lines |
| 3 | installed after `GatewayBot(...)` **plus** a `logging.Filter` on `py.warnings` | 251 lines |

**The mechanism was never established.** The decisive diagnostic — reading the
raw journal line to see whether it carries a logger name, and which — was never
run. So all three of these remain open:

- the `warnings` module writing to stderr, filters somehow bypassed
- `warnings` → `logging.captureWarnings` → the `py.warnings` logger
- coc.py or something else calling `logger.warning()` directly, in which case
  `warnings.filters` was never relevant at any point

The noise was removed **at source** instead, by taking coc.py 3.10.0, which
deletes the `utcnow()` calls. That sidesteps the question rather than answering
it.

### What this means for you

**Do not assume a `warnings` filter in this process will work.** There is no
evidence any of them ever has. If you need to suppress a warning here:

1. Get the raw journal line first — `journalctl -u wu-bot -o cat | grep -m3 <text>`.
   A logger name in the line means a logging filter; a bare file path means the
   warnings module. Those need completely different fixes and we shipped four
   without knowing which.
2. Prefer removing the warning at source (a dependency bump) over filtering it.
   That is what finally worked.
3. Measure with a `grep -c` after deploy. Every one of the four fixes above
   looked correct in the code.

---

## ESTABLISHED: `GatewayBot.__init__` reconfigures logging and warnings

Verified in hikari 2.3.5, `hikari/internal/ux.py::init_logging()`, called from
`hikari/impl/gateway_bot.py:333` inside `GatewayBot.__init__` — **not `run()`**,
and there is only that one call site:

```python
warnings.simplefilter("always", DeprecationWarning)
logging.captureWarnings(True)
```

`warnings.simplefilter()` **prepends**, so its entry lands at the front of
`warnings.filters` and beats anything installed earlier. Because it is in
`__init__`, the clobber point is the line `bot = hikari.GatewayBot(...)`, not
`bot.run()`.

This is a genuine and useful fact — it means "install the filter earlier" is
always the wrong move, since earliness is not the axis that matters. **It is
not, however, a proven explanation of the failures above**, because attempt 3
installed filters *after* the constructor and still logged 251 lines.

Constructing a `GatewayBot` also reconfigures the root logger and the log
format. Worth knowing before adding any logging configuration of your own.

### captureWarnings is not a suppression mechanism

`logging.captureWarnings(True)` replaces `warnings.showwarning`, so surviving
warnings arrive in journald wearing log formatting instead of bare on stderr.
That is why they *look* like log lines.

It cannot explain a filter failing: `warnings.filters` is consulted **before**
`showwarning` is invoked, so a matching `ignore` means no record is ever
created.

---

## Diagnosing this class of problem

Print the **head** of `warnings.filters`, not its length:

```python
print([(f[0], getattr(f[2], "__name__", f[2])) for f in warnings.filters[:3]])
```

A count says nothing — in the failing case the count went *up*, because
hikari's entry had been added.

And get the raw line before writing any fix. That is the lesson this whole
episode actually taught, and it cost four deploys:

```bash
sudo journalctl -u wu-bot -o cat | grep -m3 utcnow
```

## Related

- [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md) — the version
  pins, including coc.py 3.10.0 and why 4.0.0 was not taken.
- [todo-dashboard.md](todo-dashboard.md) — the command whose log volume made
  this worth chasing.
