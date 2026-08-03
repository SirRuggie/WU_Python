# lightbulb 3.0.3 — the Context API

We run **hikari-lightbulb 3.0.3**. Its `Context` object is narrower than people
assume, and the repo contains at least one call site proving that assumption
wrong at runtime rather than at import time.

## `edit_last_response` does not exist

`lightbulb.Context` in 3.0.3 has **no `edit_last_response` method**. Calling it
raises `AttributeError`, and Python suggests `edit_response` — which is a
different thing and not a drop-in replacement.

The proven pattern for a slow command is:

```python
await ctx.defer(ephemeral=True)
# ... slow work ...
await ctx.respond(...)          # no ephemeral= on the respond
```

That shape is used in roughly 48 places across the repo and is safe to copy.

## Why this is written down

`extensions/tasks/band_monitor.py` calls `ctx.edit_last_response` in five places
(around lines 568, 575, 585, 611, 616). Those calls are **broken at runtime** —
`/test-band-api` and `/test-war-sync` crash when they reach them. It is the only
file in the repo that uses the method.

Because it was sitting there looking like working code, it got copied into
`/fwasync check`, which then had the same latent bug. Fixed in `30601e2`
(2026-08-02) by switching to `defer` + `respond`. The `band_monitor.py` call
sites were still broken as of that date.

**The general rule this produced, which is the actually valuable part:**

> An existing in-repo call site is **not** proof that an API exists. Code that
> has never been executed has never been checked. Before copying any `ctx.*`
> call, grep repo-wide and look at the usage count.

## Usage counts as of 2026-08-02

Measured with `grep -roE "ctx\.<name>\b" extensions/ utils/ | wc -l`. Re-run it
rather than trusting these numbers after any large change.

| Method / attribute | Uses | |
|---|---|---|
| `respond` | 264 | proven |
| `interaction` | 166 | proven |
| `member` | 62 | proven |
| `defer` | 51 | proven |
| `user` | 50 | proven |
| `channel_id` | 39 | proven |
| `guild_id` | 28 | proven |
| `respond_with_modal` | 8 | proven |
| `options` | 7 | thin |
| `focused` | 4 | thin |
| `edit_last_response` | 5 | **does not exist** |

Anything in low single digits deserves suspicion. `edit_last_response` had 5,
all in one never-run file — which is exactly what the tell looks like. A thin
count is not proof of a bug, but it is a reason to check the installed version
before copying.

## Related

- [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md) — the versions
  these facts are pinned to. Recheck if lightbulb is ever upgraded.
- [component-dispatcher.md](component-dispatcher.md) — the dispatcher builds
  `MenuContext` / `ModalContext` by hand, which is its own set of assumptions
  about this API.
