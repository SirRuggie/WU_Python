# Discord identity sweep (prompt 80)

Reuses RosterDiscordIdentity as the single DiscordIdentity implementation, its DiscordContact action, existing public member_option, and the Strikes cached identity directory. Full/compact variants own avatar sizing and fallback styles; one exported name method serves native options and accessible labels. AccountIdentity is a thin adapter. Removed duplicate AccessAvatar, picker/history avatar implementations and obsolete CSS.

## Surfaces inspected

- Strikes detail, history, leave, selected leave member, import review and manual editor: shared profile; no numeric primary fallback. Strike settings itself renders role controls, with leave identities owned by StrikesWorkspace.
- Roster dialogs/workspace, account menu, Issues, signup: existing identity usage migrated to the common implementation.
- Member picker, Member time zones rows/editor/Standardize, clan leaders, Access settings/editor/history, role members and mention user suggestions: shared compact profile. Role icons remain role icons; ID search and mention insertion values are unchanged.
- Declaration last sender, Participation saved-by, Bonus saved-by, Weight trial saved-by, change history, ticket authors/list actors and player clan own-account context: shared renderer using available snapshots or batch directory data. Tickets and tools do not gain a CWL-only lookup dependency.
- Archived activity uses recorded profile data and the existing guarded archive-avatar route. No fresh directory replaces historical names.
- Signup activity and Declaration Clash player cards retain the existing DM-only DiscordContact action; they do not render a second Discord profile. Static Discord post previews and Clash player/role artwork remain distinct.

IDs remain transport keys, search terms and explicit technical diagnostics, not primary names. Text is rendered through React text nodes. Avatar URLs accept only the existing Discord CDN prefix or guarded archive route; failures reserve size and use initials. Profiles with another owner's ID are ignored.

## Read-only adaptation and authorization

Existing member option serialization supplies only id/display_name/username/avatar_url. Existing time-zone inventory, role members and mention lookup add that optional public profile projection. The bounded batch option on staff-signup-members retains its existing CWL guard. Strikes uses its own existing strikes_read-guarded members endpoint, so Strikes-only staff do not require CWL rights. Batch IDs are bounded and validated; row renderers receive results rather than fetching individually. No permission, mutation, Discord post or notification transport changes.

## Evidence

1330 frontend tests across238 files,75 focused guarded backend tests, TypeScript and build passed before final CSS layout correction. Raw-primary-ID mutant failed the loading/unavailable regression, then was restored. Shared variants, no-link/loading/unavailable, avatar failure, mismatched owner, cached-name and25-row single-batch behavior are covered. A source policy rejects Discord-ID template labels.

Isolated Member time zones browser checks at360/1440 passed with no overflow or undersized targets, including fixture-only save/stop flows. Strikes before/after screenshots at360/1440 show the raw numeric label replaced by the shared avatar/name/username/DM profile; each final sample used one batch read and no horizontal overflow. Visual inspection found missing self-contained flex styles; these were corrected before review. Evidence is retained in .local/p80-evidence and p80-timezones-layout.log. Mock fixtures prove neither live Discord delivery nor production write behavior.
