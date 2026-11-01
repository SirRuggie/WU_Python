# Declaration and Member time zones releases

PR124 and PR119 shipped together at `27b1bcc5b974b2cbc51b16fe4f98d834bd11c80d`, tag `declaration-pings-1`. The Member time zones dispatcher required the bot revision as well as backend and frontend; the earlier staged frontend/backend-only plan was not used. PR125 shipped at `390d19b3c76d105ecc675c3af2383e4ba1d94749`, tag `declaration-extras-1`, switching backend/frontend while preserving the bot.

Pings review an immutable pool-specific assignment list. Weight changes and other pools do not invalidate it; tag, owner and assigned-clan changes do. Each chunk checks fresh authorization and channel ownership. Uncertain deliveries retain receipts and are not automatically retried. Extras are informational and do not alter readiness, capacity or ping counts. Member time zones uses the existing profile worker with shared run status and cancellation.

## Activation evidence

Both releases used fresh SQLite/Mongo backups and test restores, protected counts and exact profile/settings/SQLite digests, tagged clean isolated builds, runtime imports, readiness, retained rollback assets and public asset hashes. Protected counts remained 3560 active, 301 accounts, 581 strike profiles and 274 eligible.

The first combined activation completed its 210-second lease drain and readiness checks, then failed because the coordinator lacked its local human-verification evidence file. Automatic rollback restored the prior healthy Warrior revision. Evidence validation was moved before shutdown; the guarded retry repeated the full 210-second drain and actual component/walkthrough lease checks and succeeded. These additional restarts occurred. No production database restore occurred.

The successful combined release ran bot PID1158702, invocation `902c3b82be5f4616967919a54d8c35d3`. PR125 preserved that invocation; its backend was PID1165133, invocation `b761b568861f4ecf8aadc7969e81045c`. These are historical activation observations.

## Public assets and smoke

- Combined entry `index-Ddi5L6cZ.js`: SHA256 `e4db7811a20ea688456691a6d25152e81aedee65bbd9828b56687b08fed4c27d`.
- Member time zones `MemberTimezones-BUsRDaPU.js`: SHA256 `8781f3910468daa424b3a65f47f076d6b736a06f5331db548eea2edaa0d1cc9c`.
- PR125 entry `index-nZOx6rLO.js`: SHA256 `08d019e88e07797c654325d52740d40510e4c36b1b14168d9caa35a34514fedf`.

Claude smoke262 passed at 360px: Declaration channel picker, disabled Ping until an available channel is chosen, no-ping test control, and no overflow. Member time zones showed 1447 members, Import and Standardize at the top, and nickname-derived rows. Read-only live pool fingerprints showed zero changed accounts in both published pools.

Smoke263 passed PR125 at 360px: 0/9 clans ready, 112 players not in their clan, 27 not on roster; Lazy Ping100 plus Main12 still equaled112. The Lazy-only explanation and filter were visible, with no overflow or unavailable-check warning.

No agent pressed production Send, test-send, Import, Save or Standardize. Read-only smoke does not prove Discord delivery or bulk rename completion. Ruggie performs the first real ping test. Existing Warrior and Strikes features were preserved. Local evidence is retained in `.local/declaration-pings-release` and `.local/declaration-extras-release`; review rollback coordinators against the current runtime before use.
