# Member signup card location review

Prompt 52 moves the signed-up and remaining-account cards to My signups, above
Signed-up accounts. The saved view lists every signed-up account, including
partially published rosters, omits Change signups, and retains the green card
without action buttons after signup closes. The published-ready sentence links
to My clan. Home retains its existing behavior.

My clan assignments no longer fetches linked accounts or renders signup status
cards. With saved accounts but no assigned clans it shows Not published yet,
the existing placement-date guidance, a signed-up count, My signups and Refresh.
Published assignments retain joining instructions, publication status, counts
(including awaiting placement) and clan cards. Empty signups retain their existing
grey action card. The status row wraps its metadata below its label on phones.

## Boundaries and review

The change is frontend-only. `SavedSignupStatus` reads the existing authenticated
member assignments endpoint to establish publication status; it never uses staff
placement flags to infer publication. Results are matched only to the saved
member signup tags. Season changes and unmount invalidate pending reads; read
failure keeps saved accounts visible and offers My clan without claiming published
readiness. Unavailable linked accounts suppress inferred remaining counts.
External account names remain React text, and game links retain the existing
encoded tag helper and noreferrer. No HTML rendering or mention handling was added.

The existing saved-account editor, withdrawal/pool-change policy, confirmation,
permission, dirty-navigation and save paths are unchanged. The new controls only
navigate or refresh reads: no automatic saves, retries of writes, selection edits,
or notification calls. Joining-instructions content/editor, Home, backend,
moderation and other seasons/pools are unchanged. Existing App regression suites
cover guarded navigation and account editing; the new App test verifies the
remaining-account action opens Sign up without writes.

## Validation

Evidence is retained under `.local/p52-evidence` in the review worktree. Component
checks cover published/unpublished assignments, empty signups, open/closed saved
cards, complete account lists during partial placement, unavailable links, failed
publication reads and stale season responses. Required mutation checks fail when
the signup cards return to My clan assignments or the red card survives closure.

The browser gate checks My signups open/closed and My clan assignments
published/unpublished at 360×800 and 1440×1000, document overflow, visible Open Clan
without scrolling, card ordering, navigation, zero writes and identical fixture
signup/assignment/lock counts. The new gate runs in the full layout suite; legacy
signup-card assertions now target My signups. Layout fixture ports can be overridden
to avoid existing review previews. No production ports, records or messages were
used. Native links/buttons retain keyboard semantics and visible focus styles;
this is not a complete screen-reader or physical-phone audit.
