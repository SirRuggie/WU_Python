# Roster image carousel review

Prompt 44 replaces the single-clan test dropdown with the existing Compare rail behavior. The API's clan order is preserved, so the announcement sequence's shared server ordering is also used when that batch lands. Test all and production posting behavior are unchanged.

The current clan and its immediate neighbors mount PNGs; all pages of a clan stay together. Sending remains behind the existing permission, channel picker, confirmation and test endpoint. The send control waits for every current image to load and the rail to settle. Offscreen downloads are excluded from keyboard navigation. Refresh retains a still-present selection and resets pending confirmation/receipt state.

Verification:
- Full frontend: 203 files / 1,064 tests passed. TypeScript and production build passed.
- Four targeted interaction cases cover arrow/swipe/keyboard/jump navigation, shown-clan destination, multi-page readiness, cancellation and bounded image mounting.
- Both required mutations failed tests: sending the first clan, and mounting every clan's images. Sources restored afterward.
- Isolated fake-Discord fixture at 320, 360, 390 and 1440 pixels: no page overflow, 44px carousel controls, 14px control text, no page errors, current/neighbor-only initial image requests. Reviewed first-clan, settled-swipe and two-page screenshots. Keyboard interaction is covered by the unit suite; image downloads remain full-resolution links.
- Browser verification exposed an implicit grid track growing to the carousel's intrinsic width; the posting grid now uses minmax(0, 1fr).
- One repeated frontend run exhausted the host /tmp inode pool; rerunning with disk-backed TMPDIR passed. This was a runner storage failure. The browser harness initially omitted the outer disclosure and initially captured unsettled animations; both harness issues were corrected before final evidence.

Evidence: /tmp/wu-carousel-browser.log, /tmp/wu-carousel-review/{320,360,390,1440}-{first,after-swipe,two-images}.png, /tmp/wu-carousel-full-frontend.log, /tmp/wu-carousel-build.log, /tmp/wu-carousel-mutation-{send-first,eager-images}.log.

No production writes, deployment or live Discord messages were used. Mocked sends verify endpoint selection, not live Discord delivery. Backend unchanged.

Claude review 157–158 required a same-clan selection correction before release. Choosing the current clan is now a no-op (the jump menu still closes), retaining loaded readiness, nonce and sent receipt. Added regressions for current-clan reselection, mid-scroll send blocking, and rail locking during confirmation. All three corresponding mutations were killed. Full frontend now passes 1,067 tests / 203 files.
