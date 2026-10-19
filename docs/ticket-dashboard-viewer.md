# Ticket dashboard viewer

Tickets → Browse tickets provides read-only access to open and closed ticket records, defaulting to closed tickets. Search member name, Discord ID, ticket number or stored player tags. Filter status, application type and opening date (UTC). Lists contain 20 records per page.

Applicant and staff conversations load directly from their recorded Discord threads, 50 messages per page. Latest messages refresh every 30 seconds while visible; reading older pages pauses refresh. Message search applies only to the loaded page. Attachments are links; expired attachments and deleted threads cannot be recovered here. No transcript database or full-history message search is implemented.

Access requires both dashboard Tickets permission and native Discord recruiter/admin access. Thread parent permissions and private membership are rechecked before serving cached messages. No thread is joined, reopened, modified or posted to. Messages are held only in a bounded 15-second memory cache. API responses are not browser-cacheable. Markdown HTML is disabled.

Validation: 283 backend regression tests passed; after the unavailable-thread wording update, all 8 ticket tests passed again. All 109 frontend tests passed. Production build passed. Browser checks covered archive navigation, applicant/staff switching, older messages, loaded-message search and 390px mobile layout without horizontal overflow. Live read-only checks returned HTTP 200 for both conversations on an existing approved ticket. Public homepage returned 200 and unauthenticated ticket list returned 401 after deployment.

Discord API references:
- https://github.com/discord/discord-api-docs/blob/main/developers/resources/message.mdx
- https://github.com/discord/discord-api-docs/blob/main/developers/topics/permissions.mdx
- https://github.com/discord/discord-api-docs/blob/main/developers/topics/threads.mdx
