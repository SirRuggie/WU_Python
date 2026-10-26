# Member attention and account-link recovery — 2026-10-26

## Scope

Home, Search and CWL signup read states now share a compact, goldenrod Needs
attention summary. Home no longer repeats its failed-read explanation in the CWL
next-step card, a banner, and the totals note. Verified empty links have one Link
accounts action and one guide. The guide opens with focus below the sticky header.
All explicit Home refresh controls retry a failed parent season read as well.

Search retains both account and optional staff-directory failures with a single
refresh action. Saved signups group missing links into a count and an Accounts to
check disclosure; brief row hints still explain disabled pool changes. Signup
season/account/saved-read failures have one summary, with unavailable counts shown
as a dash rather than zero. A completed signup remains successful when a later
season check fails. Existing save/withdrawal/FWA/placement warnings remain visible.

No backend, API, database, permission, notification, or signup-write logic changed.
No additional background requests or staff checks were added to member pages.
Existing read retries, private-war exclusions and roster workflows remain intact.

## Review and checks

Sol built shared/Home changes; Luna scouted and built Search/signup integration;
a separate Sol reviewed failure handling and draft protection. Review corrected
lost family-directory retry, duplicate season errors, hidden season errors on the
completion screen, partial-data signup guards, mismatched help props and mobile
focus obscured by the header. Parent browser review corrected the failed-read
signup count and clarified the affected-account disclosure label.

375 frontend tests passed, including escaped external text, summary visibility,
confirmed empty vs partial/error Home state, Search failure combinations, missing
saved accounts and preserved save safeguards. TypeScript and isolated Vite build
passed. Ten backend signup policy/entry/navigation regression tests passed; existing
aiohttp warnings remain. Validation builds used /tmp/wu-attention-build, never the
live dist directory.

Isolated fictional-data browser checks covered Home normal/empty/partial-empty,
account and season failure recovery, missing saved links and refresh recovery,
combined signup failure, combined Search sources failing, disclosure opening,
mobile menu navigation, and protected Home data clearing on 403. At 320/390/1280px,
checked long/multilingual names, focus, readable disclosure content and no horizontal
document overflow. The browser used existing signup pool review without submitting.
No API mutation was sent by the fixture checks.

## Limits

The existing native confirmation before refreshing dirty saved-signup changes was
reviewed in code. The browser automation appeared to accept that dialog, so the
cancellation branch was not verified interactively. No live signup or notification
was sent. Fixture data does not prove upstream availability or real-phone and
screen-reader behavior. Staff operational issue views remain separate and unchanged;
this is member read-recovery consolidation, not a new global monitoring system.

## Release verification

Deployed frontend revision `6b81a0bb836ed8ed5160aa190a91e975c7444a48`
after confirming the same revision on origin/main. All 241 served build files
matched the isolated build. Public HTML and browser entry script both served
`index-CsTzewF2.js`; the signed-out My signups route retained its intended login
destination. The service remained active/running without a restart.

The frontend index was replaced atomically, retaining prior hashed assets and a
private rollback index. Read-only before/after hashes confirmed all protected
records unchanged: 90 signups, 88 roster entries, one roster publication and one
season. No live signup or notification was submitted during release verification.
