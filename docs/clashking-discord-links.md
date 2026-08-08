# The Discord ↔ Clash account link API

wu-bot resolves Discord accounts to Clash player tags through **one endpoint**,
and it works in **both directions**. There is no local link table, no `/link`
command, and nothing to build.

## The endpoint

```
POST https://api.clashk.ing/discord_links
Headers: {"Content-Type": "application/json"}
Body:    ["<identifier>", ...]        JSON array of strings
```

**No authentication. No key, no token, no header.**

The array is **not a tag array — it is an identifier array**, and the server
accepts either kind of identifier in it:

| You send | You get back |
|---|---|
| player tags | `{"#TAG": discord_id_or_null, ...}` |
| a Discord ID | `{"#TAG": discord_id, ...}` — **every tag linked to that account** |
| a mix of both | both resolved in one call |

Verified 2026-08-02: a Discord ID with linked accounts returned **46 tags**;
round-tripping one of those tags back returned the original Discord ID.

## Reading the response

Two rules, both non-obvious, both required:

**1. Filter by value, not by key.** The server `#`-prefixes whatever you sent and
includes it in the response with a `null` value. A reverse lookup for
`505227988229554179` contains `"#505227988229554179": null` alongside the real
tags. Keep entries whose value equals the requested Discord ID; discard nulls.

**2. `null` and failure are different.** `{"#X": null}` means *not linked*. A
failed call means *unknown*. Conflating them tells a user with a broken API that
they have no accounts — see the failure-distinction rule below.

## What this is underneath

`api.clashk.ing/discord_links` is a thin, unauthenticated passthrough — registered
`include_in_schema=False`, so **it does not appear in ClashKing's OpenAPI route
table** — in front of `cocdiscord.link`, the shared community links database that
ClashKing, ClashPerk and others all write to. It is the source of truth for
Discord↔Clash links across the ecosystem.

`coc.py` ships a first-class client for the same database
(`coc.ext.discordlinks`, present in 3.9.1 with `get_linked_players(discord_id)`),
but that path **requires credentials** issued by hand on `discord.gg/Eaja7gJ`.
ClashKing's proxy exposes the same capability without them. Use the proxy unless
there is a reason not to.

## Failure handling — the bug this cost us

`get_discord_ids` in `lazy_cwl.py` originally returned `{}` for **every**
outcome: HTTP error, exception, and genuinely-nobody-linked. The caller never
checked. A snapshot was written regardless, with `discord_id: None` on every
player, and every downstream auto-ping then silently pinged nobody — no
exception, no warning, persisting until deleted by hand.

**Any consumer of this API must distinguish three states:**

| State | Meaning | Correct response |
|---|---|---|
| `None` (or an exception) | lookup failed, answer unknown | do not persist; tell the user to retry |
| `{}` / all-null | succeeded, nobody linked | tell the user how to link |
| populated | succeeded | proceed |

## Coverage

The database only contains links someone explicitly created, through ClashKing's
`/link`, ClashPerk's, or any other bot writing to the shared DB. A member who
never linked returns nothing, and that is indistinguishable from a failed lookup
unless the code above is written correctly.

⚠️ **It also returns links that are no longer meaningful.** One account returned
**46** tags where the owner estimated ~35 — the remainder are presumably dead or
abandoned accounts that were linked once and never unlinked. Anything rendering a
per-account list needs a position on whether to show all of them.

`/accounts` takes the completeness-first position: every returned tag gets a
row. A profile that loads shows name, Town Hall, tag, and current clan; a 404 or
temporary player-API failure keeps the raw tag visible with its status. Valid but
abandoned alts cannot be distinguished from wanted accounts, so they remain in
the list. The command never invents a "main" account because this API supplies
no such field. See [`accounts.md`](accounts.md).

## How this was nearly missed

The reverse direction was initially reported as *not existing*, from a probe with
a Discord ID that had no linked accounts. It returned `null`, which was read as
"the server just `#`-prefixes input and treats it as a tag". That is exactly what
a working endpoint returns for an unlinked account.

**Probe with an input known to be non-empty, or the negative result proves
nothing.** This rule is in [`../CLAUDE.md`](../CLAUDE.md).
