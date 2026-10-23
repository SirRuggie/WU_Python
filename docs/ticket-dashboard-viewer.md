# Ticket dashboard viewer

Tickets → Browse tickets provides read-only access to open and closed ticket records, defaulting to open tickets. Search member name, Discord ID, ticket number or stored player tags. Keep status and application type visible; applicant flags and opening dates (UTC) are under More filters. Lists contain 20 records per page.

Applicant and staff conversations load directly from their recorded Discord threads, 50 messages per page. Latest messages refresh every 30 seconds while visible; reading older pages pauses refresh. Message search applies only to the loaded page. Attachments are links; expired attachments and deleted threads cannot be recovered here. No transcript database or full-history message search is implemented.

Access requires both dashboard Tickets permission and native Discord recruiter/admin access. Thread parent permissions and private membership are rechecked before serving cached messages. No thread is joined, reopened, modified or posted to. Messages are held only in a bounded 15-second memory cache. API responses are not browser-cacheable. Markdown HTML is disabled.

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
