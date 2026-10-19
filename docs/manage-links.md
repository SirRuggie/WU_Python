# Account link management

Private administrator tools, omitted from the public help catalog:

```
/manage-links unlink user:@CurrentUser player:#PLAYER_TAG
/manage-links unlink user:@CurrentUser player:all
/manage-links transfer user:@CurrentUser new-user:@NewUser player:#PLAYER_TAG
/manage-links transfer user:@CurrentUser new-user:@NewUser player:all
```

The user options are Discord user pickers. `player` is required: enter a tag
or explicitly enter `all`. Commands execute the selected operation immediately.
Replies and the per-tag result attachment are ephemeral. Discord registration
defaults to Administrator permission and guild contexts only; execution checks
Administrator again, so command permission overrides cannot allow ordinary
members, moderators, or recruiters to use it.

## Required access

The existing `CLASHKING_API_TOKEN` is a developer credential for
`POST /v2/links/shared`. That route supports lookups and omits hidden accounts.
It does not authorize managing other users' links.

Configure `CLASHKING_BOT_TOKEN` only with a **ClashKing-issued bot credential**
authorized for account management. This is not the Discord bot token or a
Supercell player token. Contact ClashKing's maintainers to ask whether they
offer this access to third-party bots. No self-service issuance is assumed.

The management client uses the same ClashKing service and link storage:

- `GET /v2/links/{userId}` for the full inventory, including hidden links.
- `DELETE /v2/links/{userId}/{playerTag}` to unlink.
- `POST /v2/links/{userId}` with `{"player_tag":"#TAG"}` to relink.

The implementation is automatically discovered at startup. Restart and command
sync are needed to make the new slash commands available.

## Transfer and partial failures

ClashKing does not expose an atomic administrator transfer in these endpoints.
Transfer deletes the original link and creates a new **unverified** link. Old
verification, hidden status, private upgrade preferences, and notification
settings are not preserved. A failed relink attempts to restore the original
owner, but that restoration also cannot recover the old metadata.

Bulk operations remove unverified accounts first because ClashKing rejects
removing the final verified account while other accounts remain. One process
serializes link mutations, checks current source ownership before every change,
and checks destination read access before any transfer deletes a link. External
writers can still race with this bot; the API remains the authority.

The first error stops the batch, retaining a receipt of completed tags and the
failed/pending tags. An uncertain HTTP outcome is reconciled with fresh account
lists before retrying any write or restoring a source link. If ownership cannot
be confirmed, the command reports that explicitly. It stops starting new
operations after nine minutes to leave time to return the Discord response.

Development validation uses mocked API writes. A read-only check on 2026-09-28
confirmed the configured developer token returns 200 for shared lookup and 401
for the account-management inventory. No live links were changed.

API references: [OpenAPI](https://api.clashk.ing/openapi.json),
[authentication](https://github.com/ClashKingInc/ClashKingAPI/blob/main/workers/api/src/auth.ts),
[link mutations](https://github.com/ClashKingInc/ClashKingAPI/blob/main/workers/api/src/link-mutations.ts).
