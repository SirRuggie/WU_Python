# Dashboard accessibility and constrained-screen review — October 23, 2026

## Changes

- Added a keyboard-visible Skip to content link and named, focusable main landmark.
  The skip link becomes inert while the mobile navigation drawer is open.
- Browser titles identify the current dashboard page. Errors in the shared notice
  area use alert semantics; routine success/status messages stay polite.
- Confirmation focus traversal includes links, fields and summaries, excluding
  disabled, hidden, inert and negative-tabindex controls instead of buttons only.
- Added visible textarea/summary/switch focus, control scroll clearance and
  wrapping for shared notices. Search retains its existing focus-within outline.
- Mobile sidebar uses dynamic viewport height with bottom safe-area padding.
  Textareas retain 16px type on narrow screens. At short mobile heights, the
  header scrolls normally rather than occupying editing space.
- Existing responsive cards, button sizes, short-screen save bars, draft guards,
  permissions and request recovery are retained. The owner's explicit automatic
  pool GIF preference is unchanged.

## Evidence and limits

319 frontend tests and production TypeScript/build passed. Isolated browser
fixtures covered member saved signups, pool confirmation, mobile navigation and
FWA settings/message editing. Verified skip-link focus, dialog forward/reverse
focus wrap, Escape/opener restoration, drawer reverse wrap and inert background,
page titles, labeled controls, and denied editor reads with visible retry.
No live edits, signup submissions or messages were sent.

Reflow samples at 320px and short landscape 740x320 had no horizontal page
scrolling; narrow textarea was 16px with a visible outline, and the short-screen
header was static. Desktop layout was also inspected. The 320px test represents
the available CSS width at 400% zoom on a 1280px display; it is not a native browser
zoom test. Reduced viewport height approximates constrained editing space, not
an Android/iOS keyboard test. Native device keyboard behavior, screen-reader
speech output, OS text scaling and every combination of staff forms remain
unverified. This is scoped evidence, not a WCAG conformance certification.

Deployment uses static assets only; no bot or web-service restart is needed.
