# Dashboard domain migration — 2026-10-21

Canonical origin: https://dash.warriorsunited.cc
Member signup entry: https://dash.warriorsunited.cc/signup
Published member assignments: https://dash.warriorsunited.cc/assignments

The owner added the published application route on agent-forge to HTTP
127.0.0.1:8766 and registered the new Discord OAuth callback. Keep the old
Cloudflare route and Discord callback while migrating existing links.
The private dashboard environment specifies the new OAuth callback and public
URL. The owner explicitly authorized restart and full deployment, overriding
the manual deployment rule for this migration, and confirmed phone sign-in.

Legacy GET/HEAD requests redirect to a fixed new origin, preserving paths and
queries. Legacy callbacks discard OAuth code/state and start at the new home
page because old-origin cookies cannot authenticate on the new host. Legacy
writes return 409 with a sign-in instruction; they are never replayed. Local
and fixture use is unchanged. No roster or weight migration is required.

Signup announcements use the direct signup link. Default and saved legacy
roster-sheet buttons become My assignments links when campaigns are loaded or
rendered. The Lazy guide and custom copy are preserved (except known obsolete
spreadsheet directions and old dashboard URLs). Published-roster announcements
link directly to assignments using the configured public URL. Historical
Discord posts are not edited or resent; old dashboard links still redirect.

Validation: 48 focused migration/signup/authentication checks passed before
the initial restart; 14 focused announcement/signup/migration checks passed
with the final link updates. The required war reminder gate and frontend build
passed. Tests cover deep links, callback credential stripping, writes,
forwarded-host spoofing, local hosts and saved campaign-link upgrades.
The restarted dashboard served home/signup successfully; the public browser
followed the old signup link to the new domain and rendered the login page
with CWL signups as its post-login destination. The configured Discord callback
was checked without exposing state or tokens. No live test messages were sent.
