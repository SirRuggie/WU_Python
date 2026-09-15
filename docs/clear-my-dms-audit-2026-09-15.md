# `/clear-my-dms` independent audit — 2026-09-15

## Contract verified

The command is available only in the requester's one-to-one WUBOT DM. Its
warning says that confirmation permanently deletes every WUBOT-authored
message through the warning itself, preserves the requester's messages, stops
the active automatic `/todo` panel, and leaves future reminders and future
`/todo` commands enabled.

Confirm and cancel compete for one pending Mongo state row. The winning confirm
validates the user and DM again, atomically changes the row to `running`, then
stops `/todo` ownership under the scheduler's per-DM lock. The sweep uses one
fixed Discord snowflake cutoff. It filters every paginator result by the current
bot user ID and cutoff before calling the individual-message delete endpoint.
Messages by the requester, messages by other bots, and all messages created
after confirmation are outside the deletion set.

The fixed cutoff also fences a `/todo` response delivered before the clear but
waiting to claim scheduler ownership. A later `/todo` response has a newer ID
and may become the new automatic panel. Partial deletion records the count and
returns a temporary retry receipt. The receipt is newer than the cutoff and
deletes itself after 15 seconds.

## Independent evidence

The independent audit tests cover:

- a 121-message bot history split across multiple logical pages, mixed with
  requester and other-bot messages;
- exact `before=cutoff + 1` pagination and preservation of a newer bot message;
- a mid-sweep REST failure with exact partial count in state and receipt;
- exact DM channel and recipient validation;
- confirmation copy and startup extension discovery;
- cancellation without starting a purge; and
- rejection of automatic activation for a pre-clear `/todo` message.

Focused gate:

```text
.venv/bin/python -m pytest -q tests/test_clear_my_dms.py tests/test_clear_my_dms_audit.py tests/test_role_permissions.py tests/test_startup.py tests/test_todo_sessions.py tests/test_todo_dashboard.py
116 passed in 1.77s
```

`git diff --check` also passed.

## Limits

These tests use faithful asynchronous fakes and do not delete real Discord
messages. Hikari's REST client owns live rate-limit retries. A process restart
can interrupt a running sweep; its fixed cutoff and author filter still prevent
scope expansion, and the user must run `/clear-my-dms` again to finish. If a
REST failure occurs before an older `/todo` panel is reached, that message may
remain visible, but its automatic session has already been removed and the
cutoff fence prevents scheduler reactivation.
