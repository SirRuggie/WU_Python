# Discord identity release

PR #130 shipped as `3b22bf8608e61705c81370a06686ad97b6d95243`, tag `discord-identity-1`, following Claude acceptance 269. Backend and immutable frontend switched; the bot stayed unchanged. Existing Base bank, Declaration, Member time zones, Warrior and Strikes features were preserved.

One existing Roster identity implementation now serves full/compact profiles throughout the dashboard, reusing DiscordContact and public member_option. Duplicate avatars were removed. Read-only profile projections and bounded batches retain existing authorization. Strikes uses strikes_read; Standardize uses its existing authorized inventory without a CWL-only lookup. Historical ClanHistory audit and TicketConversation message-author snapshots remain name-only because their responses lack actor ID/profile.

Prompt 82 corrected missed numeric labels in Standardize starter/stopper attribution and Manual strike search results. Real numeric-ID fixtures guard both. Source policy covers nested templates, JSX and literal numeric Discord labels. Unused duplicate label wording and dangling Strikes separators were removed.

## Validation

Implementation integration passed 1,345 frontend tests across 241 files, 23 focused frontend tests, 79 guarded backend tests, TypeScript and build. Raw-primary-ID and source-policy mutants were killed. Isolated Strikes and Member time zones layouts at 360/1440 passed; before/after and unavailable-actor screenshots were visually reviewed. Mocked fixtures do not prove live Discord delivery.

Claude acceptance 269 independently passed 1,345 frontend tests, TypeScript/build and 7 network-isolated identity/Base bank backend tests. Claude did not rerun the full backend for the frontend/docs delta. The preview hash and 360px Strikes identity matched, with no raw IDs, dangling dots or console errors.

## Activation evidence

Fresh SQLite/Mongo backups and isolated restore passed, with exact protected state: 3,560 active, 301 accounts, 581 strike profiles and 274 eligible, plus profile/settings/SQLite digests. Tagged network-blocked imports, clean immutable artifacts, mocked rollback, readiness, public hashes, startup journal and unrelated configuration checks passed. No rollback, database restore or bot restart was needed.

Historical activation observations: backend PID 1216814, invocation `406add436f02452c82a4d96ce16d3615`; bot PID 1158702, invocation `902c3b82be5f4616967919a54d8c35d3`, unchanged. Public entry `index-DHlHr9-D.js` SHA256 `0078f7d54c6d49610370d0fcc84bc4b670b341976fe41ea6893e214424683317` matched the release manifest, along with affected feature assets. Evidence remains in `.local/discord-identity-release`. Review the retained rollback coordinator against current runtime before use; never restore a database blindly.

## Production smoke

Claude smoke 271 passed read-only on the released revision: current symlink, backend PID/cwd, unchanged bot and public entry hash matched. The last 15 minutes of journal contained no traceback, error or warning.

At 360px, the Strikes account from the reported screenshot showed tag, avatar, display name, username, DM link and Current line, with no raw IDs or dangling separators. Strikes lists at 360/1440 had no numeric identity labels or overflow. A fresh wide load made five distinct API requests once each, all below HTTP 400. Member time zones showed 1,447 members with shared identities and avatars, with no raw IDs.

Live Standardize starter/stopper attribution and Manual strike results were not exercised in this smoke; isolated fixtures cover those. Leave and Settings tabs were not checked in this smoke round. Import and Standardize remained closed. Nothing was pressed or written, and no live Send, test-send, import, Standardize or rename was performed.
