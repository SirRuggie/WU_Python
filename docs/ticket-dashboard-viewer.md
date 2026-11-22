# Ticket dashboard viewer

Tickets → Browse tickets provides read-only access to open and closed ticket records, defaulting to open tickets. Search member name, Discord ID, ticket number or stored player tags. Keep the permitted type scope visible; status, applicant flags and opening dates (UTC) are under Filters. Lists contain 20 records per page.

Applicant and staff conversations load directly from their recorded Discord threads, 50 messages per page. Latest messages refresh every 30 seconds while visible; reading older pages pauses refresh. Message search applies only to the loaded page. Attachments are links; expired attachments and deleted threads cannot be recovered here. No transcript database or full-history message search is implemented.

Access requires both dashboard Tickets permission and native Discord ticket-staff access plus the canonical ticket type gate. Thread parent permissions and private membership are rechecked before serving cached messages. No thread is joined, reopened, modified or posted to. Messages are held only in a bounded 15-second memory cache. API responses are not browser-cacheable. Markdown HTML is disabled.

Validation: 283 backend regression tests passed; after the unavailable-thread wording update, all 8 ticket tests passed again. All 109 frontend tests passed. Production build passed. Browser checks covered archive navigation, applicant/staff switching, older messages, loaded-message search and 390px mobile layout without horizontal overflow. Live read-only checks returned HTTP 200 for both conversations on an existing approved ticket. Public homepage returned 200 and unauthenticated ticket list returned 401 after deployment.

Discord API references:

- https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx
- https://github.com/discord/discord-api-docs/blob/main/developers/topics/permissions.mdx
- https://github.com/discord/discord-api-docs/blob/main/developers/topics/threads.mdx

## October 23 workflow cleanup

Tickets remains a read-only viewer: applicant/staff replies and approval, denial or
closure happen in the linked Discord conversation. No new decision authority,
transcript storage or delivery path was added.

- Compact joined ticket rows show status, type, opened time and flag labels; flag
  reasons are in the reader. Open tickets are the initial view. Search, filters,
  pagination and returning focus remain intact when reading a ticket.
- Applicant/Staff is one tab row. Message search and pause controls are disclosed
  on demand. Pausing or manually refreshing preserves the loaded-message search.
  Failed refreshes label the retained result; 401/403/404 clear the conversation
  and ticket identity from the reader and stop automatic polling until a retry.
- Applications & tickets settings has a searchable workflow index: entry messages,
  questions, staff responses, channels/access/timing, then optional testing. It
  reuses existing editors and endpoints. Returning restores the search, expanded
  group and triggering button focus. Narrow editors have a static save bar.
- Shared settings and publishing controls guard repeated local submissions and
  protect pending work. A posting-channel draft participates in navigation warnings
  and must be saved/canceled before saving the message. Revision conflicts retain
  edits; saving is distinct from publishing; uncertain sends are not auto-replayed.

Validation: 280 frontend tests; 1,008 ticket tests passed with two pre-existing
optional integration skips; 124 additional management/content/worker tests passed;
production frontend build. Isolated browser checks at 320px, 390px and 1280px
covered long names and escaped external text, ticket search/open/return with focus,
older/staff conversations, paused/manual refresh with search preservation, 503 and
403 conversation failures, settings search/open/return, 503 save recovery and 409
revision-conflict draft retention. Inspected layouts had no horizontal overflow.
No live ticket, permission, application decision or Discord message was changed.

Limits: no physical-device or full screen-reader certification; native discard
dialogs and actual Discord posting/delivery were not exercised in this pass. The
existing provider/archive limitations above still apply. Tests of queued delivery
and permissions are regressions, not evidence of live integration delivery.

## Prompt 261 type scope and read links

Tickets reuses the merged ListToolbar/FiltersTrigger. Search is full width;
All/Recruits/Accounts/Staff shows only permitted groups and disappears when only
one group is permitted. Recruiters can read Recruits and Accounts; the account
role only Accounts; the staff role only Staff; target-guild administrators all.
The existing dashboard Tickets grant and fresh native thread permissions/private
membership remain required. `kind=main|fwa` links still work; new links use `type`.
A forbidden explicit type is HTTP403, not an empty result. Unknown and forbidden
valid ticket IDs share403 so no unscoped existence query leaks another type;
malformed IDs and removed Discord threads retain404. List and conversation
responses use `Cache-Control: no-store`.

Rows are actual full-row links named “Read name #n, type”, with monochrome type
icons, absolute opened date and flags beside the name. A validated
`/tickets?ticket=ticket_123` read URL supports copying/new tabs. The existing
messages GET supplies authorized identity for a direct URL, without a new
endpoint or preliminary message read. Same-index local reader entries preserve
list filters and return focus through Back; dashboard route transitions and
Back/Forward preserve validated read URLs. Browser loading errors never imply a
write or bypass the type/native checks.

Current 261 checks and native fixture limits belong to its review artifact.
Historical verification above describes the earlier revisions only. No live
Discord/client/provider delivery, production permission changes or all-page
accessibility certification is inferred from fixture tests.

## Prompt 271 account labels

Known account subtypes display **Add account · Main** or **Add account · FWA**.
Missing historical `account_clan` remains unknown and uses the existing Add account
label. Both account handler roles and both recruiter roles retain account action
scope. Shared public staff-thread visibility does not grant a new dashboard
permission; existing dashboard, type and fresh Discord access gates still apply.
