# ClashKing war/CWL data, and what their own bot does

> ## THERE IS NO `/war/bulk`. DO NOT LOOK FOR IT AGAIN.
>
> Verified twice, 2026-08-03. `POST` returns **404** on both
> `api.clashk.ing/war/bulk` and `api.clashk.ing/private/war/bulk`, and the path
> appears in **neither** OpenAPI spec. It was asserted as real from a pasted
> document and is not.
>
> The only two bulk paths on the entire API are:
>
> | Path | Spec | Status |
> |---|---|---|
> | `POST /capital/bulk` | public | works, unauthenticated, **but returns 2.1 MB of full raid history per clan** and has no `limit` param |
> | `POST /ck/bulk` | private | **401 Invalid token**, and takes an array of **URLs**, not tags |
>
> **The war fan-out cannot be collapsed into one request.** Reducing calls has
> to come from caching. See [todo-dashboard.md](todo-dashboard.md).

Two things this file settles, both from primary sources rather than inference:
the real populated CWL payload shape, and how the reference `player to-do`
implementation actually works.

Read alongside [clashking-discord-links.md](clashking-discord-links.md) and
[todo-dashboard-proposal.md](todo-dashboard-proposal.md).

## Historical CWL is available — the September problem was wrong

An earlier draft of the `/todo` proposal said the populated CWL shape was
"unverifiable until Sep 1 2026" because we were out of season. **That was
wrong.** ClashKing exposes CWL history:

```
GET https://api.clashk.ing/cwl/{clan_tag}/{season}     season = YYYY-MM
GET https://api.clashk.ing/cwl/{clan_tag}/group        current season only
```

Verified 2026-08-02: `/cwl/%232UVGQU9/2026-06` returned **358 KB** of a complete,
concluded CWL season. Not every clan/season has data — most probes returned 404
`{"detail":"No CWL Data Found"}` — so **probe several clans before concluding
the store is empty.** `/list/seasons` returns the seasons ClashKing holds.

Also useful, same host:

| Route | What |
|---|---|
| `/war/{clan_tag}/previous` | past regular wars, full payloads (444 KB for one clan) |
| `/player/{player_tag}/warhits` | per-player war history |
| `/player/{player_tag}/wartimer` | the `{clans, time}` blob `/player/to-do` reuses |

## The CWL payload shape

Top level is the official `ClanWarLeagueGroup`:

```json
{"state":"ended","season":"2026-06","clans":[...8 clans...],"rounds":[...7...]}
```

⚠️ **ClashKing's `rounds[].warTags[]` contains fully expanded WAR OBJECTS, not
tag strings.** The official API returns tag strings there. So one ClashKing call
replaces the official `1 + 7×4 = 29`. Do not write a parser that assumes one
shape will work against both.

Inside, war members are the standard official shape:

```json
{"tag":"#PC9YGL0JL","name":"...","townhallLevel":18,"mapPosition":11,
 "attacks":[{"attackerTag","defenderTag","stars","destructionPercentage","order","duration"}],
 "opponentAttacks":1,"bestOpponentAttack":{...}}
```

Two facts that matter, both measured on the real payload:

- **A member with zero attacks has NO `attacks` key at all.** 840 war-member
  records, 836 with an `attacks` array — the 4 who never attacked simply omit
  it. coc.py normalises this to `[]`, so `len(member.attacks)` is safe; raw dict
  indexing is not. Same trap as regular war.
- **CWL war objects omit `attacksPerMember` entirely** — zero occurrences in
  358 KB. coc.py hardcodes `1` for CWL, which is why that works.

## What ClashKingBot's `player to-do` actually does

Source: `ClashKingInc/ClashKingBot`, `commands/player/utils.py:654+`. Read with
the operator's explicit permission.

### It does NOT use its own `/player/to-do` endpoint

`to_do_embed` computes everything from raw data — `bot.get_clanwar()`,
`bot.capital_cache` (their own Mongo), `player.clan_games()`. **The author of
`/player/to-do` does not use it in their own to-do command.** That independently
corroborates our findings that the endpoint's `war` field carries no attack
count and its `clan_games` data has been stale since 2025-07.

### The raid roster trap — they handle it, the same way we do

```python
linked_tags = [p.tag for p in linked_accounts]
for member in members:              # members = those who HAVE attacked
    linked_tags.remove(member.tag)
    ...
for player in linked_accounts:      # whatever is left attacked zero times
    if player.tag in linked_tags and player.clan is not None:
        raid_hits += f'({0}/{5}) - {player.name}\n'
```

Start with every linked tag, remove those present in the raid `members` array,
and the remainder get a zero row. **The diff is confirmed necessary and this is
the confirmed-correct approach.** Their version hardcodes `/5`, ignoring earned
bonus attacks for zero-attackers; ours should compute the real limit.

### Why no clan is shown per account

A rendering omission, not a data limitation. `get_war_hits` builds rows as:

```python
f'({len(attacks)}/{required_attacks}) | <t:{end}:R> - {player.name}\n'
```

`player.clan.tag` is used on the line directly above to fetch the war.
`player.clan.name` is simply never rendered.

### Why timestamps read "3 months ago" — NOT a bug, and not staleness

`get_war_hits` explicitly drops ended wars (`if war.end_time.seconds_until <= 0:
war = None`), so war rows always carry a **future** instant.

The "3 months ago" timestamps come from other sections that render **past**
instants by design:

- `get_inactive` — *"Inactive Accounts (48+ hr)"* → `<t:{last_online}:R>`
- `get_last_donated` — *"Capital Dono (24+ hr)"*

Those are correct data. They only *read* as staleness because the reference
implementation puts every section in one embed description, so future-deadline
rows and past-elapsed rows sit in the same wall of text.

**This vindicates separate views.** The failure was mixing two kinds of
timestamp on one page, not rendering either one wrongly.

### They solved the abandoned-accounts problem with a user setting

```python
user_settings = await bot.user_settings.find_one({'discord_id': ...})
linked_accounts = user_settings.get('to_do_accounts')   # per-user filter
```

Falling back to `link_client.get_linked_players()` when unset, with a
`player_todo_settings` UI for choosing. Relevant to us: a link lookup returned
**46** tags for an owner who estimated ~35, and the extras are presumably dead
alts.

### Their CWL/war fetch is more robust than ours in two ways

`classes/bot.py:664`:

```python
war = await self.coc_client.get_current_war(clanTag)
if war is None:
    war = await self.coc_client.get_current_war(clanTag, cwl_round=coc.WarRound.current_preparation)
```

1. **Round transitions.** `get_current_war` with `cwl_round=current_preparation`
   catches the case where the newest CWL round is in preparation while the
   previous one is still `inWar` with attacks owed. `utils/todo_data.py` handles
   the same case by scanning `rounds[-1]` **and** `rounds[-2]`, which is cheaper
   — `get_current_war` silently fans out to 2–10 calls per clan.
2. **Private war logs.** On `coc.PrivateWarLog` they look the war up from the
   *opponent's* side using their own war cache, then rebuild the `ClanWar` with
   `clan_tag=war.opponent.tag`. We have no war cache and cannot do this, which
   is why our private-log accounts become a note rather than rows.

---

# Endpoint inventory (probed 2026-08-03)

Two OpenAPI specs, and the second is not linked from the first:

| Docs page | Spec JSON | Paths |
|---|---|---|
| `api.clashk.ing/docs` | `api.clashk.ing/openapi.json` | ~public set |
| `api.clashk.ing/private/docs` | **`api.clashk.ing/openapi/private`** | 43 |

The private spec's URL is **not** `/private/openapi.json` (that 404s). It is
`/openapi/private`, discoverable only by reading the Swagger page's `url:` field.

## THE BULK ROUTE EXISTS AND WE CANNOT USE IT

```
POST /ck/bulk        (private spec, tag: "Internal Endpoints")
body: ["<full CoC API url>", ...]        # URLS, not tags
summary: "Only for internal use, rotates tokens and implements caching
          so that all other services dont need to"
```

This is exactly the primitive `/todo` wants — arbitrary CoC API URLs, any
endpoint, one round trip, server-side caching. 46 player URLs plus 30
`currentwar` URLs would be **one request instead of 76**.

**It returns `401 {"detail":"Invalid token"}`.** The spec declares no
`securitySchemes` and no global `security`, so the auth requirement is invisible
from the spec and only shows up when called. `POST /ck/generate-api-keys` exists
alongside it; obtaining a credential is a conversation with the ClashKing
operator, not something to script.

**Do not design around `/ck/bulk` until a token exists.**

## The other bulk route is a firehose

```
POST /capital/bulk   (public spec)  "Fetch Raid Weekends in Bulk (max 100 tags)"
body: ["#CLANTAG", ...]
```

Real, unauthenticated, works. **And unusable here:** it returns full raid
*history* — one clan came back as **2.1 MB / 48 seasons**, and the spec defines
no `limit` parameter. Thirty clans would be ~60 MB per `/todo` run to extract one
current weekend. `coc.py`'s `get_raid_log(tag, limit=1)` is far cheaper.

## War-related endpoints that actually exist

Public spec:

| Path | Notes |
|---|---|
| `GET /war/{clan_tag}/basic` | **"Bypasses Private War Log if Possible"**. Tiny payload: `war_id`, `clans`, `endTime` — no state, no members, no attacks. Cannot build rows from it. Worth investigating for the 17 private-log accounts. |
| `GET /war/{clan_tag}/previous` | ended wars |
| `GET /war/{clan_tag}/previous/{end_time}` | one specific ended war |
| `GET /player/{player_tag}/warhits` | per-player attack history, `timestamp_start`/`timestamp_end`/`limit`. Historical, not current state. |
| `GET /player/{player_tag}/wartimer` | |

Private spec: `GET /war-stats` returned **500** on a bare call. `GET /c/{clan_tag}`
and `GET /p/{player_tag}` are **307 redirects to in-game deep links**, not data.

**There is no `/war/bulk`.** It was asserted once from a pasted document and
404s on both GET and POST. Verify a path against the spec before building.

## Probing rule, applied again

The first probe of `/capital/bulk` and `/war/{tag}/basic` returned `{}` and
`null` — because a **player** tag was passed where a **clan** tag was required.
That reads identically to "endpoint does not work". Re-probed with a real clan
tag pulled from a live player payload, both returned data. See the probe rule in
[`../CLAUDE.md`](../CLAUDE.md) and [clashking-discord-links.md](clashking-discord-links.md).

---

# 403 `accessDenied` on `/currentwar` is a PRIVATE WAR LOG, not a failure

Observed 2026-08-03 for `#2G29002UP`, `#2RJVQLUVQ` and `#8GG` through
`proxy.clashk.ing`. **This is Supercell's documented response for a clan whose
war log is set to private.** It is not a proxy fault, not an auth fault, and not
something a token would fix.

`coc.py` turns it into `coc.PrivateWarLog`, which `utils/todo_data.py::_get_war`
catches and renders as a Private War Logs row rather than an error. Working as
designed.

## The `_response_retry` value is read, not chosen

`coc.py` sets `data["_response_retry"]` from the **upstream `Cache-Control:
max-age=` header** (`coc/http.py`, in the response-handling block), applied to
every response including 403s:

```python
delta = int(response.headers["Cache-Control"].strip("max-age=")...)
data["_response_retry"] = delta if 'realtime' not in url else 0
```

So a `_response_retry` of 600 on these means **Supercell sent
`max-age=600`** — coc.py is not hardcoding a ten-minute retry, and the number
carries no information about rate limiting. If the header is missing, coc.py
falls back to `0`.

**Do not read these 403s as a symptom of anything.** They are steady-state for
any user whose roster includes a private-war-log clan, and there are three such
clans in the current family.
