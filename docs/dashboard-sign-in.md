# Dashboard sign-in and server membership

Decided by Ruggie on 2026-11-13 (prompt 238, thread "Let non-members sign in to
dashboard").

## Rule

- Anyone with a Discord account can sign in. Sign-in does not check the
  Warriors United server (guild 644963518025826315).
- Only a CWL signup save needs the server. `POST /api/cwl/seasons/{id}/signups`
  checks membership live with Discord before it writes. Owners and editors are
  checked too. Staff endpoints that add signups for someone else are unchanged.
- Everything personal stays open to non-members: Home, Tasks (their accounts,
  their clans and wars, inside or outside the family), My accounts, My signups,
  My clan assignments, push reminders and problem reports.
- Base bank is members-only (Ruggie, 2026-11-13: "next" on the review finding).
  `GET /api/cwl/bases` (list and `?level=`) uses the cached status: `false` →
  403 "Join the Warriors United Discord server to see the Base bank."; `null` →
  503; no base data is returned in either case. The page shows that line with
  the "Join server" link.
- Withdrawing an existing signup stays allowed for a non-member. It only removes
  their own entry.
- Staff pages keep their permission checks. A non-member has no staff access,
  even with a grant; owners are the only exception.

## How it works

- `auth_callback` (`cwl_web/app.py`) still reads `/users/@me/guilds` with the
  `identify guilds` scope, but only to set `guild_owner`. A missing guild gives
  `guild_owner` 0.
- `cwl_web/server_membership.py` owns the check. The production app sets
  `app["discord_member_check"]` to the bot-token member lookup
  (`discord_member._guild_member`). Fixture and test apps have no check and
  treat everyone as a member.
- `require_server_member` runs on every signup save and never uses the cache.
  Discord 404 → 403 "Join the Warriors United Discord server to sign up."
  Any other failure → 503 "Discord membership check is unavailable. Try again."
  No signup is written in either case.
- `/auth/me` returns `server_member`: `true`, `false` or `null` (Discord did not
  answer within 3 seconds). Answers are cached per user for 60 seconds; a failure
  is never cached. `/auth/me` never fails because of this check.
- A person who joins the server can save at once: the save ignores the cache,
  and a successful save refreshes it.

## Signups page

When `server_member` is `false`, or a save was refused with the join text, the
register flow shows "Join the Warriors United Discord server to sign up." with a
"Join server" link to the permanent invite `https://discord.gg/2edDGBStax`
(approved by Ruggie on 2026-11-07). Continue and the final Sign up control are
disabled. `null` shows nothing; the server decides on save.

## Known limits

- Fixed 2026-11-13: a person with a direct staff grant who leaves the server
  loses staff access on the next request. The grant is kept for a rejoin. See
  [Dashboard access](dashboard-access.md#enforcement-and-failure-handling).
- A saved-signup pool change by a non-member is refused by the server, but the
  My signups page shows the refusal text without the "Join server" link.

## Tests

`tests/test_cwl_non_member_sign_in.py` and
`web/cwl/src/App.serverJoin.test.tsx`.
