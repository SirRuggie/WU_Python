# hikari / lightbulb versions — what actually runs

## Current state (2026-08-02)

| | Version |
|---|---|
| Python | 3.12.3 (enforced at startup — commit `85dd076`) |
| hikari | **2.3.5** on the box |
| hikari-lightbulb | **3.0.3** |
| pymongo | 4.13.2, using `AsyncMongoClient` (native async, **not** motor) |

The bot logs `A newer version of hikari is available, consider upgrading to
2.5.0` on every boot.

## `requirements.txt` pins nothing

The file lists bare `hikari` and `hikari-lightbulb` with no version specifiers.
This means:

- **A fresh install does not reproduce the running environment.** `pip install
  -r requirements.txt` today resolves to the newest release, not 2.3.5 / 3.0.3.
- The version the bot runs is whatever is installed in the venv on the box, and
  that is the only place it is recorded.

Treat the box as the source of truth for versions, not the repo.

## THE REAL CONSTRAINT: lightbulb pins hikari below 2.4.0

**Verified from PyPI, 2026-08-02.** `hikari-lightbulb==3.0.3` declares:

```
requires_dist: ["hikari~=2.3.1", "async-timeout<6,>=4", "linkd>=0.0.7", ...]
```

`hikari~=2.3.1` means **`>=2.3.1, <2.4.0`**. While lightbulb 3.0.3 is installed,
hikari genuinely cannot go past the 2.3.x line. **2.3.5 is the ceiling** — which
is exactly what the box runs, and exactly why it nags about 2.5.0 forever.

The two are a package deal. Current PyPI state:

| lightbulb | requires |
|---|---|
| 3.0.3 – 3.1.3 | `hikari~=2.3.1` (→ 2.3.5 max) |
| 3.2.2 – **3.2.5** (latest) | `hikari~=2.5.0` |

So hikari 2.5.0 + lightbulb 3.0.3 are **mutually exclusive**. Any upgrade is one
coupled move: `hikari 2.3.5 + lightbulb 3.0.3` → `hikari 2.5.0 + lightbulb
3.2.5`. There is no intermediate step.

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

## Why the box is on 2.3.5 despite that commit

`hikari==2.4.1` with lightbulb 3.0.3 installed was **never a valid combination**
— it violates `hikari~=2.3.1`. Installing it would have produced a resolver
conflict warning, and any later `pip install -r requirements.txt` against that
venv re-resolves bare `hikari` against lightbulb's `<2.4.0` ceiling and lands on
**2.3.5 — precisely the observed state**.

*Inference, not proof.* It is indistinguishable from "the upgrade was written
into the commit message as a manual step and never actually run on the box."
The venv's pip history on the Hetzner host would settle it; the repo cannot.
Either way the outcome is the same and the constraint above is what governs.

## Rules

- Verify any version-dependent API against **2.3.5 / 3.0.3**, not against the
  current online docs and not from memory.
- Do not treat the 2.3.4+ folklore as a constraint. If a real defect is found,
  document it here with a citation; otherwise it stays retired.
- Any upgrade needs the rate-limit behaviour re-checked, because that is what
  2.4.x changed and rate limiting has bitten this bot before — see
  [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md).

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
