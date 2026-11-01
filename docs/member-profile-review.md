# Member profiles PR 1 completion review

Scope: one profile per member, Warrior nickname setup, membership retention and
Compare's saved-profile preference. PR 2 import/dashboard/Standardize remains
separate. This PR adds no mutating HTTP route.

The private recruiter/session, family guild, Recruitment Team/admin permission,
actor/bot hierarchy, server owner and Manage Nicknames are checked. Final roles
are fetched and authorized inside the serialized edit, after the preview is
consumed for its exact target, actor, guild and nonce. Stale or duplicate controls
cannot rename another target or replace a newer/applying wizard. Menus stay
within 25 options and control IDs fit platform limits. Account ties, incomplete
reads and outages require a choice; no highest account is invented.

A definite Discord 400/403/404 edit refusal preserves its plain reason and says
no profile was saved. Unknown delivery stays uncertain and is never replayed.
Confirmed Discord success followed by failed profile and receipt writes gets an
independent private response identifying the split outcome. Profile success is
still reported if the setup summary cannot reload. There is no compensating or
automatic retry rename. The shorten modal prefills the bound current name, up to
the input's 32-character limit; the final preview still requires confirmation.

The profile storage owner owns revision CAS, retention indexes and durable
preview receipts. A failed index check prevents the external edit. Pre/post-edit
lease verification prevents a lost lease from committing a profile. Delayed
membership observations cannot expire a newer rejoin. A complete bounded guild
directory repairs offline transitions; unchanged present/absent rows are not
written and retain their revisions and first departure date. Partial or empty
directories mark nobody. Existing unrelated routes and collections remain intact.

Profile reads use the existing editor-authorized roster scope, cache and deadline.
Cached values survive failures; absent/malformed data falls back to nicknames
with a visible warning. Pending reads cancel on shutdown and never alter roster
drafts or placements. Official names and other external text render safely;
mentions stay disabled in Discord responses. Existing role and walkthrough steps
retain regression coverage; the obsolete three-field nickname form is retired.

## Final integrated checks

- Guarded full backend: 5,519 passed, 29 skipped, 221 subtests. The final run used
  a workspace TMPDIR after one unrelated temporary SQLite disk-I/O setup failure;
  no product workaround was added. A previously incomplete new test fake and an
  outdated outcome-response fake were corrected before passing the final gates.
- Full frontend: 1,248 passed; TypeScript and production build passed.
- Three real-Mongo cases cover revision/lease/TTL, no-churn scans, consumed
  receipts across worker restart and wrong target/actor/guild rejection. Owned
  fixture stopped. All Discord edits in these tests are mocked.
- All eight integrated layout scripts and their build passed on verified-free
  isolated ports. Profile-first Compare and seven real-builder approximate
  Warrior panels passed at 360×800 and 1440×1000 with no overflow/non-login writes.
  Screenshots were inspected; these are not actual Discord-client screenshots.
- Seven new isolated rework mutants were killed by behavioral regressions:

| Mutant | Regression |
| --- | --- |
| no-final-authorize | Revoked final Manage Nicknames prevents the edit |
| no-target-binding | Another target, actor or guild cannot consume the preview |
| no-post-verify | Lease lost during the edit never commits a profile |
| unchanged-scan-writes | Repeated complete unchanged scans perform no writes |
| confirmed-success-lost | Discord success survives both storage failures |
| definite-refusal-uncertain | A confirmed refusal retains its reason |
| applying-step-overwritten | A stale transition cannot replace an applying receipt |

The original seven feature mutants remain documented in the initial evidence.
Current evidence is `.local/p64-final-evidence`; final runtime matches the tested
integration of released polish. Final main updates after that were release docs
only. Preview hashes are independently fetched and recorded with the READY entry.

## Limits and release gates

Standard GMT labels can differ during DST; the nineteen picks do not cover every
civil offset. An unsupported location must not be saved with an invented offset.
Discord or Mongo acknowledgements can be lost after an effect; consumed receipts
and explicit uncertain outcomes require reconciliation. Tests do not prove live
Discord delivery, physical-phone behavior or assistive-technology compatibility.

Deployment still requires Claude ACCEPT, verified backup/test restore, exact
protected state, readiness, served hashes and smoke. Record the new
`member_profiles` count/size separately from the protected `strike_profiles`.
After PR 1 goes live, Ruggie must perform one real `/warrior` nickname run on
himself or an agreed test member and verify Discord plus the saved profile.
Codex posts the exact steps as a WAIT and never performs that live rename.
PR 2 release stays blocked until Ruggie confirms that transport check passed.
