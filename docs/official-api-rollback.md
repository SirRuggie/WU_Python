# Official CoC API migration rollback

This is a rollback plan, not an instruction to deploy or restart the bot.

## Known production baseline

The active production checkout was clean at `a9653af` under
`/home/botrunner/wu-bot`; the running unit is `wu-bot.service`. That revision
configures `https://proxy.clashk.ing/v1`. Its `main.py` already calls
`login_with_tokens("")`. The workspace revision `ba08d65` is an
older ancestor of production, so checking out or resetting production to that
workspace revision would discard newer production history.

Keep `COC_API_TOKEN` and `CLASHKING_API_TOKEN` in the production `.env` during a
rollback. The old proxy client does not use the official token; never send that
token to `proxy.clashk.ing`. The link token remains needed by shared-link
features.

## Rollback sequence

The official-API migration is one isolated commit above this tested
compatibility baseline. If it needs to be rolled back, first confirm the
checkout and working tree, then revert only that migration commit as
`botrunner`:

```bash
sudo -n -u botrunner -- git -C /home/botrunner/wu-bot status --short
sudo -n -u botrunner -- git -C /home/botrunner/wu-bot revert --no-edit <verified-migration-commit-sha>
```

Replace the angle-bracketed placeholder with the migration commit SHA verified
from production history; it is not a literal command argument. Do not use
`git reset --hard`, `git clean`, or check out `ba08d65`. Use the established
production procedure to apply the revert and restart `wu-bot.service`, then
confirm the unit is active and review only sanitized startup/API errors.
The revert creates a local commit in the production checkout. Record its SHA
and reconcile that commit through the normal source-control workflow so a
later deployment does not overwrite the recovery.

## Evidence and limits

- The proxy probe ran as `botrunner`, confirmed the same network namespace as
  the live process, and used the deployed venv's `coc.py` against one known
  clan and its current war. Both responses parsed; no player or Discord data
  was printed.
- The empty-placeholder login is already part of the verified production
  baseline. No rollback restart has been performed as part of this review.
- The migration must remain isolated above `a9653af`; do not manufacture a
  duplicate compatibility commit or use the older workspace revision.
