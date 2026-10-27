# Member activity logs

## Design and scope

Join/leave events for Warriors United are posted to the owner-selected channel
`1004519991648997447`. Read-only inspection confirmed it belongs to guild
`644963518025826315`, is a text channel, and the bot has View Channel, Send
Messages, Attach Files and Read Message History. No permissions were changed.

The Discord design uses one compact Components V2 container: a green join or red
leave accent, explicit Joined/Left text and direction arrow, saved display name
and username, a small avatar thumbnail, and a timestamp. Avoid banners, repeated
headers and action buttons that are unnecessary for reading a log. Mentions are
disabled. Discord controls the final client rendering.

Research consulted October 26, 2026:
- [Discord component reference](https://docs.discord.com/developers/components/reference)
- [Discord message component examples](https://docs.discord.com/developers/components/using-message-components)
- [discord.js display-component examples](https://discordjs.guide/legacy/popular-topics/display-components)

Components V2 requires flag 32768 and uses Text Display/Container instead of the
legacy content/embeds fields. Section plus Thumbnail supports an attached avatar
without a full-width image. The examples inform layout; this project continues
using its existing Hikari transport rather than introducing discord.js.

Dashboard placement: Member activity under Server tools. Use a compact newest-first
list, stored avatars and identity, joined/left text, readable dates, search and
filters. Less frequent identity/delivery details are disclosed. Keep archived
identity and avatar reads behind the same staff authorization as the history.

## Preservation and limits

Save identity at the event time and store an avatar copy rather than depending on
an external current-profile URL. If an avatar cannot be captured, show a fallback
without dropping the event. No automatic retention deletion is introduced.
Events before tracking started, or during an unrecoverable gateway/database outage,
cannot be guaranteed or reconstructed from current membership. A leave event does
not establish whether someone left voluntarily, was kicked, banned or deleted an
account; do not invent a reason.

Implementation, adversarial review, test and deployment evidence will be recorded
below after verification.

## Implementation and validation

The new permanent `settings.member_events` collection is owned by
`utils/member_events.py`; no existing data is migrated or deleted, and there is
no TTL or historical backfill. An identity snapshot is persisted before avatar
fetching. Capture/ready/send transitions use atomic claims, with stale captures
recoverable after 15 seconds. Ambiguous Discord POST results are never replayed.
The transport uses a single HTTP POST because the shared REST client's automatic
POST retries could duplicate messages. Search and avatar reads require fresh
`member_roles` access and are scoped to the configured guild.

Sol built the backend and independently red-teamed it; Luna built the dashboard.
Final review found no blocker. Relevant backend integration regressions passed
75 tests and 7 subtests. Independent review passed 18 focused backend and 21
frontend tests. The complete frontend suite, TypeScript, isolated production
build, and `tools/check_war_reminders.py` gate passed. A restricted real Mongo test
collection verified concurrent duplicate suppression, atomic claims, uncertain
receipt non-replay, cursor pagination, literal search, and private avatar reads;
its generated fixtures were cleaned up.

Isolated browser checks covered desktop, 390px and 320px, long multilingual names
and literal markup, avatar fallback, Details, search/no-match/clear, pagination,
failed-refresh retention, 403 clearing, and nonstaff route rejection. Mobile date
inputs were moved into a Date range disclosure after narrow-width inspection.
Hook tests cover delayed responses and filter parameters. No production member
records or signups were used as test fixtures. These checks are not a full
screen-reader or real-phone certification. No live Discord delivery is claimed
from mocked tests. Live channel ownership and bot permissions were verified.

When Discord omits a cached member, the latest saved join identifies a leave's
membership episode. If neither exists, deduplication uses a ten-second window.
A Discord profile link may stop working after deletion; the saved name, ID and
captured avatar remain available. An unavailable avatar uses a fallback.
