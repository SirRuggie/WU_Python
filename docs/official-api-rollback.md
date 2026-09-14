# Official CoC API migration rollback

This is a rollback plan, not an instruction to deploy or restart the bot.

## Verified production baseline

The active production checkout is the clean commit
`a9653af2db9690476aa1157c88b4ccef194e63ad` at
`/home/botrunner/wu-bot`. It uses `https://proxy.clashk.ing/v1` and already
calls `login_with_tokens("")`. That empty placeholder is the established
proxy-compatible baseline; it is not a new compatibility commit.

The development workspace revision `ba08d65` is an older ancestor of this
baseline. Never reset, check out, or deploy that workspace revision as a
rollback shortcut because it would discard newer production history.

Keep `COC_API_TOKEN` and `CLASHKING_API_TOKEN` in the production `.env` during
a rollback. The proxy client does not use the official token, and shared-link
features still require the ClashKing token.

## Rollback sequence

The direct-official-API change is one isolated commit above the verified
baseline. If it needs to be rolled back, confirm the checkout and working tree
first, then revert only that migration commit as `botrunner`:

```bash
sudo -n -u botrunner -- git -C /home/botrunner/wu-bot status --short
sudo -n -u botrunner -- git -C /home/botrunner/wu-bot revert --no-edit <verified-migration-commit-sha>
```

Replace the placeholder with the commit SHA verified from the deployed
history. Do not use `git reset --hard`, `git clean`, or check out `ba08d65`.
Follow the established production procedure to restart `wu-bot.service` after
the revert, then review sanitized startup and API errors. Record the revert
commit and reconcile it through the normal source-control workflow.
