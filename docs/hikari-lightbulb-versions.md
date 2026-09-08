# hikari / lightbulb versions — what actually runs

## Current state (2026-09-08)

| | Version |
|---|---|
| Python | 3.12.3 (enforced at startup — commit `85dd076`) |
| hikari | **2.6.0** on the box |
| hikari-lightbulb | **3.2.6** |
| pymongo | 4.13.2, using `AsyncMongoClient` (native async, **not** motor) |

Upgraded 2026-09-08 from hikari 2.3.5 + hikari-lightbulb 3.0.3 (the coupled
move described below), which also removed the startup shim in
`utils/hikari_shims.py` — see [media-hosting.md](media-hosting.md) section 3.

## `requirements.txt` pins the pair

`hikari==2.6.0` and `hikari-lightbulb==3.2.6` are both pinned, so a fresh
`pip install -r requirements.txt` reproduces the running environment exactly.
Never unpin one without the other — see the constraint below.

## THE REAL CONSTRAINT: lightbulb pins the hikari minor line

**Verified from PyPI, 2026-08-02, still true at the 2026-09-08 upgrade.**
`hikari-lightbulb==3.2.6` declares:

```
requires_dist: ["hikari~=2.6.0", "async-timeout<6,>=4", "linkd>=0.6.2", ...]
```

`hikari~=2.6.0` means **`>=2.6.0, <2.7.0`**. While lightbulb 3.2.6 is
installed, hikari cannot go past the 2.6.x line without a matching lightbulb
bump.

The two are a package deal. Historical PyPI state (2026-08-02):

| lightbulb | requires |
|---|---|
| 3.0.3 – 3.1.3 | `hikari~=2.3.1` (→ 2.3.5 max) |
| 3.2.2 – 3.2.5 | `hikari~=2.5.0` |
| 3.2.6 | `hikari~=2.6.0` (current pin) |

So hikari 2.6.0 + lightbulb 3.0.3 would have been **mutually exclusive**. The
2026-09-08 upgrade was one coupled move: `hikari 2.3.5 + lightbulb 3.0.3` →
`hikari 2.6.0 + lightbulb 3.2.6`. There was no intermediate step. Any future
upgrade must stay coupled the same way.

## The "bug in 2.3.4+" belief is RETIRED — it was a mangled memory of this pin

There was a long-carried belief that hikari must stay at 2.3.3 "because of a bug
in 2.3.4+". **There is no such bug.** hikari's changelog for 2.3.4 is 9 features
/ 3 optimizations / 1 bugfix, all additive (it *added* thread-related
`MessageType` members and the `HAS_THREAD` flag); 2.3.5 is two bugfixes shipped
one day later. Nothing was removed or renamed, no 2.3.x release is yanked, and
the issue tracker has no matching regression report.

What is true is "hikari must stay in **2.3.x**" — because of the lightbulb pin
above. The version number drifted to 2.3.3 and the reason mutated into "a bug"
somewhere in retelling.

The git history says the opposite of the folklore too. Commit `397e3ba`
(2025-09-14), *"remove broken custom REST client and update hikari to 2.4.1"*:

> Updated hikari from 2.3.5 to 2.4.1 (fixes rate limit bucket issues) […]
> Hikari 2.4.x includes proper sliding window rate limiting and bucket lock
> fixes that resolve the "greatly increased slide period" warnings.

2.4.x was adopted deliberately as a *fix*. The thing actually broken was a
hand-rolled REST client in `utils/rest_client.py` (deleted in that same commit)
which had caused 679-minute waits. **Do not rebuild a custom REST client.**

## Why the box was on 2.3.5 for so long (historical)

`hikari==2.4.1` with lightbulb 3.0.3 installed was **never a valid combination**
— it violates `hikari~=2.3.1`. Installing it would have produced a resolver
conflict warning, and any later `pip install -r requirements.txt` against that
venv re-resolves bare `hikari` against lightbulb's `<2.4.0` ceiling and lands on
**2.3.5 — precisely the observed state prior to the 2026-09-08 upgrade**.

*Inference, not proof.* It is indistinguishable from "the upgrade was written
into the commit message as a manual step and never actually run on the box."
The venv's pip history on the Hetzner host would settle it; the repo cannot.
Either way the outcome no longer matters now that the pin is 2.6.0 / 3.2.6.

## Rules

- Verify any version-dependent API against **2.6.0 / 3.2.6**, not against the
  current online docs and not from memory.
- Do not treat the 2.3.4+ folklore as a constraint. If a real defect is found,
  document it here with a citation; otherwise it stays retired.
- **Due, not yet done:** the rate-limit behaviour re-check the 2.4.x line
  demanded still applies to the 2026-09-08 upgrade to 2.6.0, because rate
  limiting has bitten this bot before — see
  [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md).
  Verify live against the running bot, not from the changelog alone.

## coc.py — pinned at 3.10.0

Taken from 3.9.1 on 2026-08-03. **There is no 3.9.2** — an earlier version of
this repo's `requirements.txt` cited one for the `utcnow` and non-JSON fixes.
It never existed. PyPI has 3.9.0, 3.9.1, 3.10.0, 4.0.0.

`v3.9.1...v3.10.0`, read from the diff rather than the release notes:

- **Removes every `datetime.utcnow()` call** — 6 in `coc/utils.py`, plus
  `coc/miscmodels.py` and `coc/http.py` — replacing them with
  `datetime.now(tz=timezone.utc).replace(tzinfo=None)`. Identical naive-UTC
  value, so no behaviour change. Ends the ~200 DeprecationWarnings per `/todo`
  run under Python 3.12.
- **`coc/raid.py` crash fix**: `max(*[...], self.stars)` → `max([self.stars] + [...])`.
  The old form raises `TypeError` when a raid member has destruction but no
  recorded attacks, because `max(int)` is not iterable. A live crash in the
  `/todo` raid path.
- **`coc/http.py`**: `(await resp.json())["keys"]` → `.get("keys", {})`.
  Hardens login against a non-JSON response — relevant because every call goes
  through the `proxy.clashk.ing` third party.
- `coc/enums.py` adds new troop/spell/equipment names to the ordering lists
  (additive only). `coc/abc.py` gains day/minute/second upgrade-time precision.
- Everything else is static game-data JSON, **inert here**: `main.py` sets
  `load_game_data=LoadGameData(default=False)`.

Nothing was removed from the public API. All six client methods used in this
repo — `get_clan`, `get_clan_war`, `get_league_group`, `get_league_war`,
`get_player`, `get_raid_log` — still exist, as do `login_with_tokens`,
`LoadGameData`, `base_url` and `key_count`. `requires-python` is `>=3.10.0`;
the box is 3.12.3.

### 4.0.0 exists and was NOT taken

Released 2025-12-06. A major, per `docs/miscellaneous/migrating_to_v4.rst`:

- static data is **always** loaded now, regardless of `LoadGameData`
- lists that lived in `coc.enums` moved to `coc.constants`
- `Troop`/`Hero`/`Spell` attributes changed type or were removed
  (`Troop.training_time` gone), `Pet` split out of `Hero`
- `Client.create_army_link` removed
- minimum Python raised to 3.10

Our surface is narrow enough that it might well be fine — `WarState` and
`ExtendedEnum.__str__` are unchanged in v4, checked directly. But coc.py is
used across `/todo`, the FWA tooling, `lazy_cwl` and clan info, so a major bump
is its own project with its own testing, not a pin edit.
