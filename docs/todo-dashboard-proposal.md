# `/todo` — player to-do dashboard: research & proposal

Research deliverable, 2026-08-02. Six parallel workstreams, findings adjudicated
against primary sources. **No implementation code was written.**

Durable stack facts extracted from this research are in their own files —
[components-v2-in-hikari.md](components-v2-in-hikari.md),
[component-dispatcher.md](component-dispatcher.md),
[deployment.md](deployment.md). This file is the proposal.

---

# PART 1 — FINDINGS

## 1.1 The blocking unknown: there is no Discord → tags lookup

**wu-bot has no account-linking mechanism of its own.** No collection in
`utils/mongo.py` stores player tags against a Discord user.
`extensions/commands/family_links.py` is a role/clan assignment panel despite the
name — rule it out.

The only linking call in the repo is `lazy_cwl.py:43-75`:
`POST https://api.clashk.ing/discord_links`, unauthenticated, **tags → Discord
IDs**. That is the reverse of what `/todo` needs.

**The reverse endpoint does not exist publicly.** Verified against
`https://api.clashk.ing/openapi.json`: 47 paths, none matching discord/link.
`/discord_links` is absent from the spec entirely — registered
`include_in_schema=False` — and its whole implementation is a one-line passthrough
to `coc.ext.discordlinks`.

**But the direction exists one layer up.** `api.clashk.ing/discord_links` proxies
`cocdiscord.link` (the shared community links DB) using **ClashKing's own
credentials**. coc.py already ships the client:

```python
await link_client.get_linked_players(discord_id)   # GET /links/{discord_id}
```

Credentials are issued by hand on the Clash API Developers Discord. ClashKing
chose to expose only the forward direction publicly.

### Three routes

| | Route | Cost | Risk |
|---|---|---|---|
| **A** | Request our own `cocdiscord.link` credentials, call `get_linked_players` directly | One method call; coc.py already installed | Depends on a third party granting access; also **removes the current free-riding on ClashKing's credentials** |
| **B** | Local `player_links` collection + a wu-bot `/link` command with CoC API-token verification | Full control, works when ClashKing is down | ~35 manual link operations per power user, each needing an in-game token |
| **C** | **Hybrid (recommended)** — sweep family clan rosters, POST all tags to `/discord_links`, reverse-index the result. Local table as override | **Free, needs no user action**, and `lazy_cwl.py:894-997` already implements exactly this loop | Only finds accounts **currently in a family clan**; misses alts parked elsewhere |

## 1.2 What can actually be computed

| Section | Verdict | Call | Per unit |
|---|---|---|---|
| **War hits** | ✅ **Live, clean** | `get_current_war(clan)` | 1 / clan |
| **CWL hits** | ✅ **Live, same call** | same — falls through to CWL automatically | 2–10 / clan in season |
| **Raid weekend** | ✅ **Live during the weekend** | `get_raid_log(clan, limit=1)` | 1 / clan |
| **Clan games** | ❌ **Not in the API at all** | — | — |

**War + CWL share one call.** `get_current_war` returns the regular war, or falls
through to the current CWL round if `state == notInWar`. Split them in the UI on
`ClanWar.is_cwl`. Never call `get_clan_war` and `get_league_group` separately.

**Attacks used has no attribute** — it is `len(war.get_member(tag).attacks)`.
A member with zero attacks has no `attacks` key in the JSON at all; coc.py
returns `[]`, so `len()` is safe but raw dict access is not.

### ⚠️ The raid trap — verified live, 2026-08-02 mid-weekend

`capitalraidseasons` `members` **only contains players who have already
attacked.** Measured on `#2PPCL2GYP`: 42-member clan, raid `state: "ongoing"`,
**14 member entries, zero with `attacks: 0`**.

The population a to-do list exists to show is *structurally absent from the
response*. **You must diff the clan roster against the raid members list;
absence means zero used.**

Attack limit is `attack_limit + bonus_attack_limit`, and the denominator moves —
`bonusAttackLimit` flips 0→1 when a player finishes a district. So a row can read
"5/5 done", disappear, then legitimately reappear as "5/6".

**Private war logs block war but not raids.** Verified: clans returning HTTP 403
on `/currentwar` returned 200 with full member data on `/capitalraidseasons`.
Treat the raid section as available even when war is not.

### ❌ Clan games cannot be built without our own snapshots

**There is no clan games endpoint.** Verified: `/v1/clans/{tag}/clangames` → 404.
Nothing on `Clan`, `ClanMember` or `Player` exposes it.

The only signal is the `Games Champion` achievement, whose `value` is a
**lifetime cumulative** counter (observed: 245,780 against a target of 100,000 —
it keeps incrementing past completion, so it works as an odometer).

**This event's points = value_now − value_at_event_start.** That requires a
scheduled snapshot taken *before* the event opens on the 22nd. Miss the window
and that account is unrecoverable for the whole event — there is no backfill.
Second flaw: points earned in a *different clan* still land in the diff.

**ClashKing's precomputed alternative is dead.** Their `player_stats_db` carries
exactly the right shape — `clan_games["YYYY-MM"] = {clan, points}` — but the
newest season key for sampled WU accounts is **2025-07**, thirteen months stale,
while `last_online` on the same documents is current. Verified independently.

## 1.3 The `/player/to-do` endpoint does not save us

`GET https://api.clashk.ing/player/to-do?player_tags=...` — public, no auth, up
to 50 tags per call — already computes a to-do list. It is the reference
implementation's own backend. It is **not sufficient**:

| Field | State |
|---|---|
| `current_clan` | ✅ useful — and it is the field the reference implementation omits from its *output*, so that gap was always a rendering choice |
| `war` | ❌ **no attack count.** `{clans, time}` only — byte-identical for a player with 2 attacks used and one with 0 |
| `raids` | ⚠️ `{}` for non-attackers — same trap as above, so empty for exactly the people who need reminding |
| `cwl` | ⚠️ has counts, but the handler has a live `AttributeError` → 500 when a clan's war isn't found in the round |
| `clan_games` | ❌ dead since 2025-07 |

It also fans out to 3–7 sequential upstream calls per tag and is
`cf-cache-status: BYPASS`. Measured: 30 tags = 4.8 s outside CWL.

**Verdict: build it ourselves via coc.py.** Use `/player/to-do` for nothing, or
at most for `current_clan`.

## 1.4 The stack

**wu-bot does not talk to the Clash API.** `main.py:58-63` sets
`base_url='https://proxy.clashk.ing/v1'` and `main.py:101` calls
`login_with_tokens("")` — an empty token. The proxy discards auth and substitutes
its own rotated Supercell keys.

**`key_count=10` is dead configuration.** Verified in coc.py `client.py:448`:
`login_with_tokens` sets `correct_key_count = len(tokens)` — i.e. **1** — *before*
`_create_client` reads it. Effective throttle is `1 × 30 = 30 req/s`, 33 ms
enforced spacing. That floor, not network latency, sets the wall clock.

**coc.py's FIFO cache is already on** — 10,000 entries, TTL from the proxy's
`Cache-Control`. Measured: clans **600s**, currentwar **95s**, players **60s**,
raid seasons **120s**. A second dashboard open within 60s costs **zero** calls.

### ClashKing is one dependency, not three

Raw data (`proxy.clashk.ing`), account linking (`api.clashk.ing/discord_links`)
and the to-do endpoint all sit in one Cloudflare zone on one account. No status
page, no SLA, no auth relationship.

**A fallback that shares a DNS zone with the thing it backs up is not a
fallback.** The only genuine insurance is credentialed direct access to
`api.clashofclans.com` — a ~4-line change plus a Supercell key bound to the
Hetzner box's IP.

**We are in breach of their only ask.** `api.clashk.ing`'s terms say *"Please
credit if using these stats in your project, Creator Code: ClashKing"*. There is
**zero user-facing credit** anywhere in wu-bot. A footer line fixes it.

`proxy.clashk.ing` is sanctioned nowhere — its README documents self-hosting
only. Their live `/stats` shows ~90M requests/day, so our footprint is a rounding
error and this is tolerated rather than stolen. But there is no agreement to
point at if they add auth tomorrow.

## 1.5 DM delivery is not blocked — and may already work

hikari 2.3.5 exports `ApplicationContextType` / `ApplicationIntegrationType` with
builder setters; lightbulb 3.0.3 accepts `contexts` and `integration_types` as
class kwargs. `dm_permission` is deprecated and hikari never implemented it.

**Verified at lightbulb `sync.py:120-123`:**

```python
if guild is hikari.UNDEFINED:
    builder = builder.set_integration_types(...).set_context_types(
        builder.context_types or list(hikari.ApplicationContextType))
```

`list(ApplicationContextType)` is `[GUILD, BOT_DM, PRIVATE_CHANNEL]`, and
`main.py:55` registers globally. **So every wu-bot command is probably already
DM-invokable.** Confirm with `GET /applications/{app_id}/commands`.

Watch for boot churn: if Discord strips `PRIVATE_CHANNEL` (it requires
user-install), lightbulb sees a diff every boot and re-registers everything.
Declaring `contexts` explicitly avoids it.

**Custom emoji work in the bot's DM.** Discord explicitly grants
`USE_EXTERNAL_EMOJIS` in DMs with the app's own bot user, documented on the
`app_permissions` field. The whole `utils/emoji.py` set renders. That grant does
**not** extend to group DMs — another reason to stay off user-install.

**⚠️ The house header pattern crashes in a DM.**
`clan/dashboard/dashboard.py:44` does
`bot.cache.get_guild(ctx.guild_id).make_icon_url()`. In a DM `ctx.guild_id` is
`None` → `AttributeError`. Resolve the guild icon from a constant.

## 1.6 Dispatcher

`/todo` is **not blocked** on phase 0 commits 3 or 4 — provided it stores no
state. See Part 3.

**⚠️ One colon only.** `raw.partition(":")` splits at the first colon and
everything after is the state key. `manage_roles.py:366`/`:385` build
`remove_roles_page:{action_id}:{page}`, the lookup misses on the composite, and
the handler returns "Session expired" — **that pagination has never worked.**
Documented in [component-dispatcher.md](component-dispatcher.md).

---

# PART 2 — DESIGN

## 2.1 Component budget — two requirements conflict

A Section holds 1–3 Text Displays and **exactly one** accessory. Four nav buttons
as Section accessories = **12 components**.

| Shell | Components |
|---|---|
| Container + header Section + separators + pager | 11 |
| 4 nav Sections | 12 |
| **Total** | **23 of 40** |

That leaves 17 for rows:

| Row style | 20 rows | Verdict |
|---|---|---|
| One string select, 25 options | 2 | ✅ 25 actionable rows |
| Grouped Text Displays | 1–4 | ✅ not individually clickable |
| One Text Display per row | 20 | ❌ caps at 17 |
| One Section per row | 60 | ❌ caps at 5 |

**Per-row Sections are dead regardless of nav styling** — demoting nav to a plain
ActionRow buys 7 components, which is 2 more Section rows, not 15.

## 2.2 The shell

```
╭─ Container (accent = RED_ACCENT) ─────────────────────────────╮
│ ┌ Section ────────────────────── [Thumbnail: guild icon]      │
│ │ ### Your To-Do · 35 accounts                                │
│ │ Data as of 14:32 · max 2 min old                            │
│ └                                                             │
│ ── Separator ─────────────────────────────────────────────    │
│ ┌ Section ─────────────────────────────── [ War Hits ]  ←btn  │
│ │ ▸ **12** accounts owe war attacks                           │
│ ┌ Section ─────────────────────────────── [ CWL ]             │
│ │ ▸ **3** accounts owe CWL hits                               │
│ ┌ Section ─────────────────────────────── [ Raids ]           │
│ │ ▸ ✅ all caught up                                          │
│ ┌ Section ─────────────────────────────── [ Clan Games ]      │
│ │ ▸ not available — see notes                                 │
│ ── Separator ─────────────────────────────────────────────    │
│                                                               │
│ [ Select: 20 actionable rows for the current view ]           │
│   ⚔️ MainAcct · Warriors United · 0/2 · ends in 4h            │
│   ⚔️ AltOne   · WU Reborn      · 1/2 · ends in 4h             │
│                                                               │
│ ── Separator ─────────────────────────────────────────────    │
│ [◀] [Page 1/2] [▶] [⟳ Refresh]                                │
╰───────────────────────────────────────────────────────────────╯
```

Count badges live in each nav Section's **Text Display**, not the button label —
button labels cap at 80 chars and re-rendering a label churns the button.

The current view's button is `disabled` (confirmed supported on Section
accessories) and can carry an emoji.

## 2.3 A row

```
⚔️ MainAcct · Warriors United · 0/2 · ends <t:1785551000:R>
```

- **Account name** — from the player payload
- **Clan** — the field the reference implementation omits, and the whole point
- **Attacks used** — `len(member.attacks)` / `attacks_per_member`
- **In war** — implied by presence; non-actionable rows are omitted entirely
- **Time remaining** — `<t:UNIX:R>`, a **future instant**, so it ages correctly
  forever with no bot involvement

## 2.4 Timestamps — the rule that avoids the reference implementation's failure

`<t:UNIX:R>` is safe for a **fact about the world** (war end, weekend end). It is
never safe for **message freshness** — that is exactly how you get "3 months ago".

Freshness uses an absolute format plus a static bound:
`Data as of <t:…:T> · max 2 min old`.

## 2.5 Pagination

Binds at **25 rows** (Discord select-option cap). 35 accounts → 2 pages at 20/page.
Page and view live in the **state-free custom_id**, never in a stored document.

## 2.6 Empty state

`All caught up.` Nothing else.

---

# PART 3 — ARCHITECTURE

## 3.1 Stateless by design

**`/todo` stores nothing server-side.** `custom_id` encodes view and page; the
user comes from `ctx.user.id` on the interaction.

```
todo_view:war|2          # exactly one colon; "|" sub-encoding is free
```

This is the single highest-leverage decision in the design:

- **Dissolves the dispatcher sequencing constraint.** Nothing to migrate, so it
  does not matter whether `component_state` lands before or after.
- **Immune to state pruning.** The dead expiry guard and the missing-kwarg
  failure cannot be reached — there is no document to be missing.
- **Zero contribution to unbounded growth.** No `button_store` documents at all.
- **The ticket-ID landmine is structurally impossible.**
- **No ownership check needed.** A stray clicker sees *their own* data, because
  identity comes from the interaction. The residual risk is `edit=True`
  overwriting the owner's message — impossible in a DM, per-user in an ephemeral.

## 3.2 Data flow

```
/todo (DM)
  └─ defer(ephemeral)                      ← 3s ack, 15min window
     └─ resolve tags        links:{user_id}     in-process, 6h TTL
        └─ get_player × A   coc.py FIFO         60s TTL, free
           └─ dedupe to clans
              ├─ get_current_war × C   coc.py FIFO  95s
              └─ get_raid_log × C      coc.py FIFO  120s
                 └─ diff roster vs raid members    ← the trap
                    └─ filter to actionable only
                       └─ render view + 4 badge counts
```

## 3.3 Cost

35 accounts across ~12 clans:

| | Calls | Wall clock |
|---|---|---|
| Outside CWL | **59** | 2.5–6 s |
| During CWL | ~167 worst case | 4–14 s |
| Second open within 60s | **0** | instant |

`get_current_war` silently costs 2–10 calls during CWL. Do **not** use
`LeagueGroup.get_wars_for_clan` — it chains every round, 28 requests.

No Mongo on the read path. coc.py's FIFO cache plus a small in-process dict for
derived values and **negative results** — on a quiet Tuesday three of four
sections are "nothing to do", and that answer is stable for days.

## 3.4 Phasing

| Phase | Ships | Gate |
|---|---|---|
| **0** | Resolve linking (route A, B or C) | Without it there is no feature |
| **1** | War hits + CWL hits — one call each, shares `get_current_war` | |
| **2** | Raid weekend — needs the roster diff | Raid weekend to test against |
| **3** | Refresh + cooldown, ClashKing attribution footer | |
| **4** | Clan games — **only if** the snapshot job is accepted | Must deploy before a 22nd |

**Relative to the ticketing project:** `/todo` is independent. Being stateless, it
does not touch `button_store`, does not need `component_state`, and adds no
dispatcher requirement beyond what commits 1–2 already deliver.

---

# PART 4 — RISKS & OPEN QUESTIONS

## 4.1 Risks, by severity

| # | Risk | Mitigation |
|---|---|---|
| 1 | **No linking mechanism.** Without Discord → tags there is no feature. | Decision required — route A, B or C |
| 2 | **ClashKing is a single point of failure** for data *and* identity, one Cloudflare zone, no SLA, no status page. | Credentialed direct CoC access is the only real insurance |
| 3 | **Raid section shows the wrong people** if the roster diff is missed — the API omits non-attackers. | Diff roster vs raid members. Verified trap. |
| 4 | **Clan games is unbuildable** without a scheduled snapshot that must succeed on one specific morning. Miss it and the month is lost. | Drop from v1 |
| 5 | Private war logs return 403 on `/currentwar`. | Show "war log private", do not silently drop |
| 6 | Extra-colon custom_id silently breaks pagination. | One colon; page in the custom_id's sub-encoding |
| 7 | `ctx.guild_id` is `None` in a DM — the house header pattern crashes. | Guild icon from a constant |
| 8 | Boot-time command re-registration churn if Discord strips `PRIVATE_CHANNEL`. | Declare `contexts` explicitly |
| 9 | `coc.py` is unpinned in a repo that pins hikari/lightbulb. Deployed version unverified. | Pin it |

## 4.2 Decisions needed

1. **Linking route** — A (request credentials), B (local table + `/link`), or
   C (roster sweep, recommended as the free first step).
2. **Clan games** — drop from v1, or accept a monthly snapshot job whose failure
   mode is silent and unrecoverable?
3. **Nav-as-Sections costs 12 components and rules out per-row buttons.** Keep the
   styling and use a select for rows, or demote nav to an ActionRow?
4. **ClashKing attribution** — add the footer? We are in breach of their only ask.
5. **Credentialed CoC fallback** — worth obtaining a Supercell key bound to the
   Hetzner IP?

## 4.3 Could not determine

- **The populated `cwl` shape** from any source — we are outside CWL season
  (next: Sep 1–9 2026). Re-probe then.
- **`proxy.clashk.ing` rate limits** — undocumented; the Go source contains no
  limiting code, but Cloudflare fronts it. "Unlimited until it isn't."
- **Whether `/todo` already works in DMs** — settled by one call to
  `GET /applications/{app_id}/commands`.
- **The deployed coc.py version** — `requirements.txt` is unpinned. Settled by
  `/home/wubot/wu-bot/venv/bin/pip show coc.py`.
