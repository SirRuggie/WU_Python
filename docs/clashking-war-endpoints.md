# ClashKing war/CWL data, and what their own bot does

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
