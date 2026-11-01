# Member profiles PR1 completion review

Scope: bounded profile storage, Warrior nickname wizard, membership retention and
Compare's saved-profile preference. PR2 import/dashboard/Standardize work remains
separate. There are no new mutating HTTP routes in this PR.

Authorization checks cover the private recruiter's session and family guild,
existing Recruitment Team/admin permission, actor/bot role hierarchy, the server
owner, bot Manage Nicknames, and fresh member/role reads before the edit. The
existing editor-authorized roster route alone includes scoped profile metadata.
Unknown controls/forms cannot consume a newer preview. Mentions are disabled;
preview text is rendered safely and nickname/control length limits apply.

Account lookup uses existing combined links and official player fetching. Highest
TH/tie/no links/partial/hard upstream failure cases are covered. Menus stay within
25options and page ties; unsupported data never silently chooses a main account.
Country ranking commits only an aggregate flag count, not a member directory.

Concurrent edits use a shared transient lease and profile revision CAS. Preview
consumption precedes Discord, and unknown delivery is never replayed. Tests cover
stale revisions, failed Discord edits leaving no profile, import protection of
staff/warrior data, lease contention, TTL retention and a restarted worker reading
a consumed receipt after Discord success/storage uncertainty. A delayed departure
cannot override a newer rejoin, and a failed summary read cannot turn a confirmed
save into a reported failure. No compensating or automatic retry rename is added.

Profile reads are scoped and nonblocking, preserve cached values/drafts/placements,
warn on unavailability, and cancel on shutdown. Valid saved zones precede parsed
nicknames in both sorting and labels; malformed/unavailable values fall back.
Existing role setup/walkthrough functionality retains its regression coverage.
The unused legacy nickname formatter/form was removed or explicitly retired.

Checkpoint evidence (final full rerun pending): prior guarded backend5,502passed/28skips/221subtests;90focused current backend tests; full frontend
1,226tests/228files; TypeScript/build; three real-Mongo cases (fixtures stopped);
seven mutation kills (tie silently chosen, failed edit saves, import overwrites
staff, nickname overrides profile, stale departure overrides rejoin, retention
index guard bypassed, stale result overwrites a newer preview). Seven
approximate Discord panels at360×800/1440×1000 and profile-first Compare fixtures
at360×800/1440×1000 passed with no overflow or non-login writes. Screenshots were
inspected. These previews reuse the real builders and existing DiscordPreview
renderer but are approximate; mocked edits do not prove live Discord delivery.
The full integrated layout lane is recorded separately before READY.

Remaining limitations are explicit: standard GMT labels can differ during DST;
the19choice menu does not represent every civil offset; an unsupported location
must not be saved with an invented offset. Discord may accept a request before a
storage or transport acknowledgement is lost; the consumed receipt and visible
uncertain outcome require staff reconciliation. This is not an actual Discord
client, physical-phone or assistive-technology audit. No live rename was tested.

Deployment remains gated by Claude ACCEPT, backups/test restore, protected state,
readiness and smoke. Confirm the new collection is empty or has only recognized
profile rows before creating its TTL index. Record member_profiles count/size
separately from the protected strike_profiles581baseline. No Standardize is
implemented or pressed by this PR.

Daily membership reconciliation repairs departures missed while the bot was
offline. It trusts only a complete bounded directory including the bot itself;
partial/empty/error reads never mark absences. It preserves the first departure,
uses observation ordering and does not masquerade as a new staff profile edit.
Receipt CAS belongs to the profile storage owner, and an older operation cannot
mark or replace a newly opened wizard. Retention-index failure refuses the edit
before Discord. These final fixes are covered by the focused and real-Mongo lanes;
READY waits for the fresh full backend gate.
