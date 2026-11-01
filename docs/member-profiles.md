# Member profiles and Warrior nickname setup

Prompt62 is delivered in two PRs. This first PR adds storage, Warrior setup and
Compare preference. Import and the staff dashboard/Standardize workflow belong
to the second PR and are not activated here.

`member_profiles` has an explicit Mongo route. One document keyed by Discord ID
holds the standard zone ID/label/offset, country/flag, chosen account tag, source,
editor/time, revision and `left_at`. A bounded `membership_at` observation timestamp
prevents a delayed departure from overriding a newer rejoin. The storage owner is
`utils/member_profiles.py`; callers do not write this collection themselves.
`left_at` has a90-day TTL. Returning members clear it; departed members are marked
only in the Warriors United guild. There is no profile history collection.
Records are small (normally below1KiB); report actual count/size before and after
release. No existing collections or routes migrate.

All profile edits use revision checks. Transient60-second member edit leases live
in the existing component-state collection and expire after2minutes. They
serialize competing sessions/processes without adding profile history. Discord
transport stays in the Warrior extension. A save consumes its preview before any
external edit, validates the expected revision, edits Discord once with a20-second
bound, then writes the profile. A failed or uncertain Discord response saves no
profile. The consumed preview never retries automatically, including after a
restart. If Discord may have accepted a change, check the current nickname before
making a new preview. A later storage failure is also surfaced for reconciliation;
there is no automatic compensating rename. A saved profile remains reported as
saved even if the subsequent setup-summary read fails.

Warrior retains Recruitment Team/administrator authorization and checks actor,
bot role hierarchy, server owner and Manage Nicknames again before saving. Profile
setup is restricted to the family guild. Every form rechecks the private session's
recruiter, target and guild. Leaving the wizard invalidates its controls. Concurrent
or stale controls cannot consume a newer preview.

Names use the existing combined link resolver and official player service. A
unique highest Town Hall in a complete result autofills. Ties, missing profiles,
provider outages and incomplete results require a choice or typed name; no tie is
silently broken. Account menus page24choices plus Type a name. With no loaded
accounts, a Type a name button opens the private modal (Discord cannot open a
modal after acknowledging an asynchronous account lookup).

Country menus have24common choices plus Other, accepting a two-letter code.
Choices are ranked by aggregate flags from287linked-owner nicknames in the
read-only release observation (US62, IN45, CA14, GB9, AU8, BD7, DE/PH5, etc.);
ties use country code. See member-profile-country-ranking.json.
Multi-zone countries ask for a zone. The nineteen standard labels are GMT-8,
-7,-6,-5,-4,-3,GMT,+1,+2,+3,+4,+5,+5:30,+6,+7,+8,+9,+10,+12, with regional
explanations. The profile zone ID is the stable lowercase GMT label, not an IANA
civil-time identifier. A GMT label describes standard time and can be an hour off
during daylight saving; grouping is unaffected. Regional/dependency exceptions
ask for a supported standard label explicitly. Do not choose an inaccurate
offset for an unsupported region; leave the setup unsaved and ask staff.

Preview shows `Name | GMT-5 🇺🇸`; oversized names offer Edit/shorten and cannot be
saved above32characters. Mentions are disabled in responses. Saved profiles take
precedence in Compare's timezone sorting/card labels; nickname parsing remains
the fallback. The scoped profile read runs in the background, has an8-second
bound and30-second cache, preserves drafts/placements and cancels on shutdown.
Only the existing editor-authorized roster route includes these values. Failed
profile reads retain cached values, fall back to nickname labels when absent,
and show a Compare warning.

The nickname import, staff page, restartable Standardize jobs and bounded old-name
receipts are reserved for PR2. Only staff may press Standardize in production;
agent smoke checks will stop at its preview.

Adversarial checks cover delayed leave/rejoin ordering and a successful save
followed by an unavailable summary. The first cannot set a newer member's TTL;
the second still reports the confirmed save. If Discord confirms but Mongo does
not, the UI explicitly reports that split outcome and consumes the preview.
A real-Mongo receipt test creates a fresh worker wrapper after that uncertainty
and proves the mocked Discord callback is not repeated. This is evidence for
restart behavior with mocked transport, not proof of live Discord delivery.

Retention repair runs once after startup and daily thereafter (hourly retry on
unavailability), using a complete bounded directory that must include the bot.
Partial, empty or failed directory reads do not mark departures. This repairs
missed offline events without sliding an existing departure date. Membership
observations advance their own ordering timestamp while preserving the last
actual profile-edit date. A current member edit also records presence.

Preview consumption and final receipts use the profile owner's nonce/identity
CAS. Returning home or opening a newer wizard prevents an older operation's
result from replacing it. A failed retention-index check refuses external edits.

## Staff dashboard and import (PR 2)

The Member time zones page uses the existing `member_roles` dashboard permission.
Every new route checks it, and the bot checks current dashboard grants again
before applying queued work. All server members are listed, including bots as
read-only entries, with Saved, From nickname, Unknown and Missing states.
Saved profiles sort ahead of the nickname fallback; unknown offsets never become
zero. Search, status filtering and west-to-east sorting stay local to this page.

Staff may choose a linked official account or type a name, use the same country
and GMT choices, and save a profile with or without a reviewed nickname change.
An imported offset outside the nineteen picks remains available as one extra
option. Profile-only edits do not rename Discord members. Fresh target/actor/bot
roles and the exact old nickname are checked inside a serialized external edit;
revision and lease checks surround it. Already matching nicknames cause no
Discord edit. Definite refusals, unknown acknowledgements and confirmed Discord
success followed by unconfirmed storage have distinct outcomes.

The import reads a complete bounded guild directory, classifies recognized zones,
unknown suffixes and missing zones, then fills absent profiles without renaming
anyone. Existing staff, Warrior and imported decisions are preserved. Reruns are
safe after partial progress. The shared language-neutral parser data and vectors
keep Python import and TypeScript Compare labels aligned. Valid numeric offsets
within plus/minus fourteen hours are canonicalized, including offsets outside
the menu. An absent or ambiguous country flag stays null; staff must supply a
country before Standardize can include that profile. Import timeout/failure may
leave some confirmed profile writes; the result says it did not finish, never
claims a completed count, and explicitly says nicknames were unchanged.

Standardize begins with a complete old-to-new preview, including every skipped
member and the reason. No preview read occurs while its disclosure is closed.
The server stores one ten-minute preview per staff member in TTL component state.
Confirmation consumes it by nonce and selection hash; unticked members never
become work items. A consumed confirmation cannot recreate an expired/pruned run.

The durable manifest and child receipts live in existing `bot_config`. There is
one global active lane, at most ten thousand selected members and a two-megabyte
manifest limit; an oversized preview is rejected instead of truncated. Only one
deterministic member child is released at a time, with a fresh fifteen-minute
request lifetime and a minimum three-second spacing gate. The existing worker's
polling adds latency; this is not a promised throughput. Pending work resumes
after restart. Running, completed and uncertain calls are never reset or replayed;
uncertain results require manual Discord/profile reconciliation.

Old nickname receipts retain at most twenty terminal runs for at most thirty
days, together with their terminal children. Standalone profile save/import
receipts have the same twenty/thirty-day bound. Active work is never pruned and
unrelated management sections are untouched. The scheduler performs retention
cleanup even when no run is active. Durable profile documents still overwrite in
place; no unbounded profile edit history is introduced.

PR 2 release must wait for Ruggie's successful real `/warrior` test after PR 1.
Agent production smoke stops at Standardize preview: only staff confirm a run.
The isolated UI fixture simulates its HTTP transport and never contacts Discord
or Mongo; real-Mongo tests separately exercise receipt, selection and restart
semantics. Neither proves live Discord delivery.
