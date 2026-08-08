# `/accounts`

`/accounts` is the private inventory of every Clash player tag that ClashKing
currently links to the invoking Discord user.

## What it shows

Each loaded account row contains:

- Town Hall emoji and explicit Town Hall number
- player name, linked to the official in-game player profile
- player tag
- current clan, or `No clan`

Loaded profiles are sorted by Town Hall descending, then player name and tag.
There is no "main account" distinction because the link API does not provide
one. Pages contain at most 20 linked tags and use Components V2 buttons.

## Privacy

The command is self-only. In a guild its interaction response is ephemeral. In
a DM it is an ordinary interaction response because Discord has no ephemeral DM
messages. Adding a target-user option requires a separate privacy and permission
decision; do not infer that authority from the current command.

## Completeness policy

The source of truth is `utils.clash_links.resolve_tags(discord_id)`. Every tag it
returns gets exactly one inventory row:

```text
linked tags = loaded profiles + profile-not-found tags + temporary failures
```

This reconciliation is required because `todo_data.fetch_accounts()` correctly
omits `coc.NotFound` profiles for `/todo`, where a dead account cannot owe work.
Silently applying that behavior to an inventory would make `/accounts` claim to
show everything while dropping old links.

- A live profile shows its full account row.
- `coc.NotFound` keeps the raw tag visible as `Player profile not found`.
- A transient lookup failure keeps the raw tag visible as `Account couldn't be
  loaded` and adds a retry warning.
- During observed Clash maintenance, the maintenance explanation replaces the
  generic failure warning.

Valid but abandoned alts still load and therefore appear normally. The bot
cannot determine whether a valid linked account is still meaningful to its
owner, so it does not guess or hide one.

## Failure semantics

The link resolver's three states remain distinct:

- `None`: the link service failed; say the answer is unknown.
- `[]`: the lookup succeeded and the user has no links; explain ClashKing
  `/link`.
- populated list: load and reconcile every tag, retaining partial results.

The command shares `/todo`'s link cache, ten-minute player-profile cache, and
eight-request concurrency bound. Each new `/accounts` invocation revalidates the
link list so an account linked moments ago appears immediately. A two-minute
in-memory result cache keeps pagination from repeatedly requesting NotFound or
temporarily failing profiles; rerunning `/accounts` bypasses that page cache.
