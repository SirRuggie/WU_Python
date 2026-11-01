# Declaration location loading polish

Queued in Claude smoke 280 and scoped for review in entry 282. This frontend-only change replaces provisional zero counts with Checking locations while assigned accounts lack checked location records. Settled incomplete results say Locations unavailable. Confirmed counts remain visible during refresh, and a confirmed zero remains a real zero.

The same derived checking count drives the pool-wide Ping control, clan readiness labels, summary and pool tabs. Live preview is disabled while that pool has unknown locations; Copy mentions is disabled for an incomplete clan. Existing notification confirmation, receipts, authorization, destinations, channel picker and transport are unchanged. No API calls or polling were added.

Checks: pending to ready, settled unavailable, cached refresh and confirmed zero; no live preview while partially unknown; 1,360 frontend tests across 242 files, 31 focused cases and TypeScript/build; three mutants caught (provisional Ping zero, provisional clan zero, enabling Ping with some unknown accounts). Isolated read-only fixture states pending/unavailable/recovered pass at 320/360/390/1440 with no overflow or non-GET calls and 44px affected controls. Narrow/wide screenshots visually reviewed. No live Discord delivery is tested or claimed.

Release is held per entry 282 pending Ruggie's approval or a later approved release. This branch has not been deployed.

Review preview: port 44581, `declaration-extras-preview.html?locations=pending` (or `unavailable`; Refresh recovers loaded data), entry `declaration-extras-preview-S1xcfTHB.js`, SHA256 `1d5751d0fdd0a491930f1ffbdef921359ed331b72b1cf5c89066668601c3a8c3`. Evidence `.local/loading-layout`, `.local/full-fe-release.log`, `.local/build-ready.log`, `.local/mutants.json`. The public page/roster asset hashes were fetched and still match nickname-review-1; this polish has not been activated.
