# Staff sign-in destination review — October 23, 2026

The URL migration already allowed known staff pages through successful OAuth.
This pass closes two remaining gaps: the signed-out screen now names the staff
page using the navigation labels, and failed OAuth callbacks append the error
parameter correctly when the destination already includes season/step parameters.
Supported publication review/announce tabs and numeric CWL seasons survive retry.
Other local filters and unsaved edits are not persisted by this change.

Unknown/external destinations stay excluded by both allowlists. OAuth state
remains one-time, server-expiring and cookie-matched. A destination does not grant
permissions: navigation falls back to Home with a clear access explanation and
staff endpoints keep their existing authorization. No session lifetime, scope,
credential, role or owner privilege changes.

Validation: 59 backend tests plus 49 subtests, covering successful staff return,
failed return with queries, expired state, forged/external destinations, and
protected routes. Updated an obsolete route test that still expected the retired
Manage signups destination instead of its canonical Roster destination. All 318 frontend tests and the production build passed. Isolated browser confirmed signed-out staff
page labeling, retry URL, mobile layout, and an unauthorized member returning
to Home with the access explanation. No live Discord OAuth authorization
or staff mutations were performed. Existing aiohttp warnings remain.
