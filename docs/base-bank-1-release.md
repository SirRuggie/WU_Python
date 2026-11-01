# Base bank release

PR127 shipped as `3b27a735ac8d348a8dd88be36a9dc1eb3c044378`, tag `base-bank-1`. Backend and immutable frontend switched; bot PID1158702/invocation902c3b82be5f4616967919a54d8c35d3 stayed unchanged. Existing features were preserved.

The member page reads existing fwa_config. Plain keys mean merged defenses; _new keys mean non-merged. Validated Clash layout links, contained war images, lazy plain-text details and one horizontally scrolling Town Hall selector reuse existing account-display and supported-level helpers. Details-only levels are excluded; /bases survives sign-in.

## Gates

Fresh SQLite/Mongo backups and isolated restore passed. Protected counts remained3560 active,301 accounts,581 strike profiles,274 eligible, with exact profile/settings/SQLite digests. Tagged network-blocked imports, clean immutable1920-file backend archive, frontend build, mocked rollback, readiness, public entry/feature hashes and unrelated service configuration passed.

The first activation guard stopped before any service switch because one replacement departed flag changed during the build. The evidence was retained; a new backup/test restore and guarded retry passed. No legitimate state was overwritten, no database restore ran and no bot restart occurred. Activation backend PID1206767/invocationb5c5f8017a074abbb807a619245d132b is a historical observation.

Public entry index-DPMDZkPf.js SHA256 af7753f938cfeee388a9e31d20506d225545c9ad3286f3ac4f1e943e5eca5251 matched the release manifest. The coordinator also verified BaseBank and other affected feature assets. Evidence remains in .local/base-bank-release.

## Validation and smoke

Implementation integration passed1339 frontend tests,16 focused frontend,4 guarded backend tests,TypeScript/build. Skipping frontend link validation was caught by a behavioral test; source was restored and builds repeated. Seven isolated browser states at320/360/390/1440 passed, including ten chips on one row and active selection visible. Narrow/wide screenshots were reviewed.

Claude smoke268 passed at360×800 and1440×1000: war image loaded, merged first, Copy base control, closed details, sidebar entry, two wide cards and no horizontal overflow. Both links pointed to link.clashofclans.com; neither was opened. All API requests on the fresh load returned200. Older console errors were absent on fresh load; their cause was not established. One transient Todo clan-history Mongo warning was outside Base bank, with no traceback.

Production member-role default Town Hall selection was not tested in Claude's staff session; isolated fixtures cover it. No live copy link was opened or production action written. Rollback retains the prior390 backend/frontend; review the saved coordinator against current runtime before execution, and never restore a database blindly.
