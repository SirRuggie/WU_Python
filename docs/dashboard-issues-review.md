# Dashboard Issues readability review — October 24, 2026

Replaced repeated large cards with a compact report list. Issue type, local time,
reference and affected Discord identity are visible. Profiles reuse the roster
identity component: avatar, display name, username, Discord ID and profile/DM link.
Technical request/response information remains behind a native disclosure.

Search matches names, usernames, IDs, references, issue labels and request paths;
a type filter narrows results. Initially renders 25 reports with explicit Show more,
while search covers the entire returned history. Existing 30-day/500-report storage,
recording, rate limiting and routes are unchanged. Profiles are current Discord
identities, not historical name snapshots.

The owner-only endpoint resolves the existing cached/paged Discord directory once,
with a five-second bound, and returns only identities present in the reports.
Unrelated members and role information are excluded. Missing/departed members keep
the saved ID. Directory failures return the issue history plus an unavailable
profile status. Cancellation propagates; no profile requests run per report.
Unauthorized callers cannot trigger identity resolution.

Refresh preserves loaded reports on a transient failure with explicit old-data
wording; 401/403 clears them. Effect cleanup ignores abandoned responses. The page
has no mutations beyond an explicit outbound Discord profile link; no live messages
or issue-record changes were performed during testing.

Validation:
- 52 backend tests passed covering issues, identity decoration and foundation
  permissions/CSRF/signup behavior. Added owner-only profile lookup, affected-user
  filtering, role stripping, unavailable directory and cancellation regressions.
- All 330 frontend tests passed; production build passed into an isolated directory.
- Browser fixture checked at 1280px, 390px and 320px: compact rows, avatar/name/ID,
  long-name wrapping, no horizontal page overflow, labeled search/type controls,
  combined filtering, expandable request details and 25-row initial rendering.
- Failed refresh preserved reports and search; missing profiles showed saved IDs;
  revoked access removed all rows. Native controls/disclosures and 44px action
  targets retained. No separate screen-reader speech or physical-device pass.
- Live read-only Discord directory lookup resolved both protected owners with
  avatars. No production permissions, notifications or roster data changed.
- Whitespace checks passed. Existing framework warnings remain.

Deployment: implementation revision da60898 pushed to origin/main. Web runtime
import/startup passed and restored Mongo revision 7870; service active/running with
zero automatic restarts. Public entry assets and the Issues JavaScript/CSS chunks
returned 200 and matched the isolated build byte-for-byte. Production fixture mode
remained disabled; signed-out protected API probes were rejected. No bot restart
was required. Temporary browser fixture was stopped after validation.
