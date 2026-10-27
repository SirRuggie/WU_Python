# Moderation history and log settings

## Scope and design

Extend the existing member archive with confirmed kicks and bans, and let staff
configure each event's Discord destination. History stays the landing view; Log
settings is a separate focused view. Preserve `/server/member-activity` as an alias
for `/server/moderation` and retain the existing API and saved records.

Default join/leave posting remains channel `1004519991648997447`. New kick/ban
posting starts off until staff selects a destination. Disabled Discord posting
does not remove archived history. Text channels use compact Components V2 cards;
forum channels use a compact embed starter, the documented forum-message shape,
with one searchable post per event. Do not attempt a second notification format
after an ambiguous create response.

Use green Join, red Leave, amber Kick and stronger red Ban labels. Color supports
explicit action text. Keep the saved profile/avatar, join date and relative event
time. Reason and moderator information are included only when known; dashboard
secondary details expand without cluttering the history list. Discord profile
links can become unavailable after deletion; saved identity remains readable.

## Primary references

Reviewed October 26, 2026:
- https://docs.discord.com/developers/resources/audit-log
- https://docs.discord.com/developers/events/gateway-events
- https://docs.discord.com/developers/resources/channel#start-thread-in-forum-or-media-channel

Member removal alone does not prove a kick or ban. Confirm kicks from an audit
entry and bans from their dedicated event. An audit reason or actor must be tied
to the correct action and target. The bot already requests GUILD_MEMBERS and
GUILD_MODERATION. Read-only production checks confirmed audit-log access (200),
channel inventory (200), and six forum channels. No moderation action was taken.

The final validation, deployment evidence and remaining limitations will be
recorded after implementation review.

## Validation

- Sol backend implementation and independent Sol adversarial review; Luna UI.
  Review fixed missed-unban/reban recovery and prevented nearby audit facts from
  replacing an explicitly identified ban's moderator or reason.
- Affected backend/transport suite: 91 tests and 62 subtests passed. Transport
  tests cover text V2, forum multipart starter/avatar/tag receipts, inert mentions,
  and no second POST after an ambiguous error. These are not live delivery tests.
- Full frontend suite: 92 files / 396 tests passed; TypeScript and isolated Vite
  build passed. Required war-reminder validation passed.
- Restricted real Mongo test collection verified CAS settings, concurrent event
  dedupe/claim, uncertain no replay, pagination/search, saved avatar and size bound;
  temporary test collection cleaned afterward.
- Isolated browser checked desktop, 390px and 320px layouts, ban filtering,
  channel search and forum required tags, successful save with reduced response,
  conflict preserving edits, unavailable channel inventory preserving settings,
  and forbidden responses clearing settings. No horizontal overflow at narrow
  widths. Synthetic external markup rendered as text. Browser automation stalled
  on the existing unsaved-navigation confirmation, so that cancellation path is
  not claimed as browser-verified; the existing shared navigation guard is used.

## Limits and operational behavior

A removal and its confirmed kick/ban are separate records; a leave does not
assert voluntary departure. Late audit enrichment updates history but an already
posted card may omit late reason/actor information. Missing gateway events cannot
be guaranteed to backfill. Unknown join dates remain unknown; moderation cards
label older saved dates as last known. No actual moderation actions or test posts
were performed in production, and forum delivery still needs observation after
staff configures a forum and a real event occurs. Existing history is retained;
no signup/roster schema or data migration is involved.

## Release verification

Deployed implementation `92f12117b21c6099cfd1513910f165e55952de65` to both
checkouts. Bot runtime imports passed and member-events extension loaded in the
new process with no current-process error markers. Bot and web services active.
Public `/server/moderation` HTML and entry/moderation assets match the reviewed
isolated build; signed-out history and settings requests return 401. Older hashed
assets were retained during atomic index installation.

Private pre-release SQLite backup retained locally. Post-release digests match
for 93 signups, 93 roster entries, one publication and one season. Live log settings
retain the existing join/leave channel; kick/ban posting remains disabled. Archive
indexes have no expiry. No data migration or live notification test occurred.


## Forum post destinations — October 27, 2026

Moderation settings now include accessible active forum posts in channel search.
Pasting an unlisted numeric ID offers an explicit Look up action; the staff-only
read endpoint checks the post and its parent forum before selecting it. Saved
archived posts are resolved during reload. Save and delivery recheck server
ownership and inherited permissions, including Send Messages in Threads.
Locked posts and private/non-forum threads are excluded. Unlocked archived posts
can receive replies; Discord automatically unarchives them on send (see
[Discord thread documentation](https://github.com/discord/discord-api-docs/blob/main/developers/topics/threads.mdx)).
Selecting a forum channel still creates new posts; selecting a post sends replies.
No storage migration, automatic retry, mention policy, or receipt changes.

Validation: 34 backend tests plus 7 subtests across member events, moderation
settings and transport; 6 focused frontend tests; TypeScript and isolated Vite
build passed. Backend regressions cover parent ownership, staff visibility,
missing thread-send permissions, locked posts, private threads, malformed IDs,
lookup authorization, save revalidation, and reply transport. Existing tests
cover stale settings revisions, cancellation, duplicate events, and uncertain
send receipts. Isolated browser fixtures verified name search, keyboard Enter
selection, ID lookup, and explicit Save. Desktop and 320/390px mobile inspections
checked readable controls, visible focus, results, and no horizontal overflow.
These checks do not establish live Discord delivery or full screen-reader support.
No production settings, live messages, or served dashboard assets were changed.
