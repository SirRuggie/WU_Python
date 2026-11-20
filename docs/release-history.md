# Release and rollback history

## Official WU crest and list toolbars — November 20, 2026

Released PRs [#406](https://github.com/SirRuggie/WU_Python/pull/406) and
[#407](https://github.com/SirRuggie/WU_Python/pull/407) as frontend
`0643a4ffefcc505595e0765e12f77de980054911`, tag
`wu-crest-toolbar-256-258-1` (tag object `eb3f2fcb7e3b0b10d8ffe4074c9fbc8d0eb2e789`).
Shaka approved the exact source heads in handoff 1237 and 1253; owner release
instructions are 1238 and 1243. Handoff 1253 allowed this combined release while
259 continued separately.

The normal staging helper built a clean tagged isolated checkout. All 187 public
asset hashes matched the staged manifest; config returned 200 and signed-out
seasons returned 401. Entry `assets/index-B7EbeV8l.js` SHA256:
`f3c3dc048dc35416fadc769aa567dc85a643c75e342ea0590113633dbfabd486`.
The bot's same-path logo was separately backed up and replaced with approved
SHA256 `0192ac66fe7bc3438362660390ad7461e5a393ada248c621659aa7389d89065d`
(438,771 bytes, uid 1002, gid 1004, mode 0644). Its owning workers exited and
were reaped before subsequent guards. No restart, Discord/R2 request, database
restore or data repair occurred.

Backend remained `4035d1592dc4a9c0fff59233d5d305a5b759cd84`, PID 691416;
bot code remained `af99e27deecf33fad827749276fb4f40139c4bbb`, PID 329298;
gateway PID 307279 remained unchanged. Only the bot logo path became dirty.

Verified backup serves as the explicitly named BEFORE snapshot. Separate POST
verification, strict comparison and final journal/runtime window passed before
DONE 2277. Main signup/assignment/lock counts stayed 23/23/23; Lazy 147/146/131.
Protected Mongo metrics stayed 3,562 active strikes, 301 active accounts,
625 streak profiles, 260 eligible accounts and 489 member profiles. All 76 SQL
tables were observed; existing session/claim and timestamp policies passed with
strict remaining counts, schemas, pools and publication state. All positive
staff business projections across 81 Mongo namespaces remained exact; no 1245
content-edit exception was needed. Member events increased from 5,939 to 5,941
and unknown-owner changes were recorded under the existing 1107 policy; this is
not a claim that all background data or row contents were unchanged. Whole
Town Hall and legacy FWA documents and indexes remained exact.

Evidence: `.local/256-retry-1245-actual/completion-256-258.json`, SHA256
`b2d0eaefb9f80f85c5a1f42c31666e3b8a544685c8c06693a04d1ee9c5ce0f6f`.
The original 256 attempt failed on a staff-field comparison and was rolled back;
its failure evidence remains frozen and was never relabelled as passing. This
fresh attempt used its own verified before/after captures. Shaka's read-only
production smoke follows DONE separately.

Retained frontend rollback: `f7e072bee7e2665988266d86c67f5f9b79cb90e9`.
Retained logo backup:
`/home/botrunner/wu-logo-release-256-258-0643a4ffefcc505595e0765e12f77de980054911`,
intent SHA256 `95ff7fafd38fd29a4ddbdbdcd3dc3138692578f5d3d1775bbeb7d02a2a2cf017`.
Any later recovery requires fresh current-state guards and code/asset-only
rollback. Never replay historical coordinators or restore the database.

## Reading this record

The latest dated release facts supersede older uses of “current”, “standby” or
“rollback target” below. Frontend, backend and bot can advance independently.
These are retained observations from each release boundary, not fresh production
probes or permission to rerun a completed coordinator. Before any new release or
rollback, verify the actual process revision/cwd, service identity and served
asset hashes, then use the newly scoped, reviewed procedure. Roll back code;
never restore a database to roll back code or reverse approved data corrections.

The latest retained boundary is the completed November 18 M bot-only release:
bot `4d6c53637d0c38f3fa869203e70ccd3d5d2b6c8e`; backend remains K
`a8fb4c524c0b84572fc6e28a955dae3fe6a34ad4`; frontend remains
`14c5e5acc6551f803ca1ae1837c0a57655719de0`. M's retained bot-only fallback is
K `a8fb4c524c0b84572fc6e28a955dae3fe6a34ad4`. See the dated M record below
for its failed first attempt, completed retry and ongoing first-day observation.
These component-specific recorded facts do not replace fresh verification before
a future release or recovery.

## November 18, 2026 — 239M background health, completed bot-only retry

M PR [#378](https://github.com/SirRuggie/WU_Python/pull/378) completed at
03:40 EST on November 18. The bot release is
`4d6c53637d0c38f3fa869203e70ccd3d5d2b6c8e`, tag `background-jobs-health-1`
(object `8dc2dd873f3cf1ae4212bc0517cb20a6b61432dc`). The parent recorded bot
PID 3063066, invocation `d8fd9f19d9464d27be7dfd86c6cb1f33`. Backend K
`a8fb4c524c0b84572fc6e28a955dae3fe6a34ad4` retained PID 3040395 and invocation
`ce22d702169c4552bd5859eb3bfc1f64`; frontend
`14c5e5acc6551f803ca1ae1837c0a57655719de0` and gateway PID 307279,
invocation `25b0336632ea45e59828bcec964a1d3b`, were unchanged. These are saved
release-boundary facts, not fresh production probes by this documentation update.

The retained **bot-only** code fallback at this boundary is K
`a8fb4c524c0b84572fc6e28a955dae3fe6a34ad4`. Backend and frontend remain on their
own dated revisions; this is not a universal rollback target. Before any future
release or recovery, verify the then-current identities and retained assets.

### First M attempt 203 failed; K recovery was separate

The first attempt checked out M but its parent-account source checker raised
`PermissionError` on the tracked `.claude/agents/builder.md` before starting the
M service. No M process or M auth GET started. Immediate independent bot-only
code recovery restored K after the full 210-second drain; separate readiness,
all 184 public hashes and the post-rollback protected-data assessment passed.
The original pre-start proof remained preserved before a new actual recovered-K
proof bound the rollback capture. Recovery did not retroactively pass the failed
M attempt. No database restore or backend action occurred.

The failed completion remains accepted:false at
`.local/239m-release-evidence-203/completion.json`, SHA256
`827ae8e8d40f2e695d69645a71340649e66d49c45fe678539b184f72ce729749`.
The original missing-tag preflight failure also remains retained; fetching the
exact approved tag and a separate fresh preflight did not erase that failure.

Shaka entry 1114 accepted only the source-check function change: read all tracked
bot files as botrunner through owner-account Git `rev-parse`, clean `status`,
`ls-tree` and one batch `hash-object`. A real pre-stop check covered all 2597 K
Git blobs; the M start checked all 2601 M Git blobs. This is Git blob equality to
the approved tree, **not new production SHA256 proof**. The isolated clean-tag
2601-file SHA256 source proof remained separate. No permissions were changed,
no unreadable source was skipped, and no new coordinator or gate bypass was used.

### Retry 216 completed under the existing direct sequence

Shaka entry 1112 approved head
`6957dce0d8dd5a1886f48dd85837683935510799` on K with exact combined tree
`c6c40df77f072acf20b8f0181e20ea812138bf15`. His full-suite result was 8614
passed, 134 skipped and 544 subtests. This is Shaka-attributed evidence, not a
Codex rerun. Existing private runtime imports passed for 44 bot modules; no new
backend imports were run. The reviewed operations base had 185 literal checks;
the single owner-reader increment was accepted directly in 1114 without a new
review round. No full frontend or backend suite was repeated for this retry.

The parent used the K190/192 individual release steps with backend steps removed:
verified fresh source and runtime bindings, backup/pre capture, owned bot stop,
full 210-second drain, fresh history guard, owner-account source verification,
M startup/readiness, one auth smoke, post capture/binding, assessment, final
readiness, public hashes and final HOST/journal proof. No backend staging,
restart, switch or configuration write occurred. Copied inline source bodies
are retained as executed-inline source, not separately executed files or an
independent process log; shared presentation labels do not mean independent
processes.

One immutable ONLINE pre-capture also served as the verified backup; these were
not independent captures. Pre SQLite SHA256 was
`725092b9f144ec4b597047f0fad00069da23f9384270a82593695af4cc2676f0`;
post SHA256 was
`cda33e145838e3a94b15a506502de1265edd1fb5f8f6a64d4d98aac6ae2c7b38`.
All 76 SQL table counts, column definitions, schema, pools and six publication
records matched; strict staff-content checks passed. Main remained 23 signups /
23 assigned / 23 kept; Lazy remained 147 / 146 / 131. The third number is
`SUM(kept)`, not an independently measured lock count. Sessions stayed 207→207
with zero D6 removals. The original comparator actually returned PASS with ten
permitted clock-related changed rows. Raw digest differences were confined to
`participation_group_observations` and `participation_sync_settings`; this is
not an all-raw-digests-exact claim for the release interval.

All 79 Mongo positive staff projections, namespace inventories and index
metadata matched. Component state changed 6→9; member events 5569→5558 with
22 eligible removals and 11 additions; world-clock runs 1671→1672 with one
eligible removal and two additions. Twenty unknown-owner changed namespaces
were recorded. No TTL causation, unchanged background-data or all-row-content
claim follows from these observations.

Exactly one signed-out auth GET returned 302 to Discord without following the
redirect or sending a Cookie. Across that auth window, all 76 raw SQL digests
and `oauth_states` remained exact. Final bot/backend/gateway invocation journals
had zero errors. All 184 public asset hashes matched the unchanged frontend;
the three critical hashes remain those listed in the dated K record below.
No operator database restore, manual index repair, application data write or
Discord test post was performed. Ordinary runtime changes are recorded separately.

At 03:31 EST, Shaka entry 1115 independently reported **PASS (runtime)**: bot PID
3063066 on M, zero tracebacks and zero “Background job failed” entries since
03:15 EST, and public config 200. These are Shaka's observations, not new Codex
probes. The existing five-minute handoff's first-day journal observation was
anchored to the actual M invocation and remains **ACTIVE until
2026-11-19T08:18:12.915367+00:00**. It is ongoing observation, not a 24-hour PASS;
no new daemon or configuration was created.

Frozen accepted completion:
`.local/239m-ownerhash216/runtime/239m-release-evidence-216/completion.json`,
SHA256 `c1b8e5a424b6a5ce265bbfbbad2657c03ffb1a4d689ea8e23e302a6e895bbb9f`.
Portable report: `.local/239m-final218/review.html`, SHA256
`2435f62cc365a332adacbf6a86f03e419309f771d0c6a0599f991827a63c3f4c`.
Final artifact review 219 accepted saved bytes and safe aggregates STATICALLY;
it is not independent live, process-log or visual proof. The report retains the
full failed-attempt and preparation history. Shaka's exact smoke text is retained
as `shaka-smoke-1115.txt` alongside the completion, SHA256
`68a481b9f64627ff0a0624cbf3e5458fd1e32ff86b6eb0371cd781cf64f807e6`.

Mongo snapshots are sequential, not transactional. Immutable SQL snapshots
cannot detect deletion followed by identical reinsertion. No UI, assistive
technology, physical-device, live OAuth, live Discord delivery or production
latency proof is claimed. No production probes were repeated for this docs update.

## November 17, 2026 — AF first activation failed; old code recovered

The AF attempt ran on November 18 UTC (November 17 local time). The recorded
boundary after code recovery at 21:19 EST was:

| Layer    | Recovered revision                         | Recorded process                                                                         |
| -------- | ------------------------------------------ | ---------------------------------------------------------------------------------------- |
| Frontend | `14c5e5acc6551f803ca1ae1837c0a57655719de0` | External `current` symlink; gateway PID 307279 unchanged                                 |
| Backend  | `469dafea617498918c2891d203391cd9c93bf688` | PID 2979913, invocation `7942244a768d4950b6b06e0e64ec2aae`, cwd `backend/469dafea…`      |
| Bot      | `29f9823def09e0d55bb0e7e9a22752ef97515851` | PID 2980779, invocation `f0e30a723c18445b882859d92969e7fe`, cwd `/home/botrunner/wu-bot` |

These are parent-recorded recovery observations, not fresh checks by this docs
update or a universal standby. They supersede the earlier process identities
below while retaining G, H and 240's successful dated release facts. AF was
**not completed**; K remained approved and held for serial release after AF.

AF PR [#376](https://github.com/SirRuggie/WU_Python/pull/376), merged revision
`47d186440d24ff5ff9f07001acc0b31b37911777`, tag
`dashboard-store-off-loop-1`, had source approval in Shaka entry 1099. Its
retained merged suite passed 8495 tests, with 134 skipped and 544 subtests;
fresh isolated runtime imports passed without repeating that suite. Earlier
operations drafts 89/95/99/103/112 failed or remained incomplete in review and
were never executed. The plain 114 integration was the first actual AF
production activation attempt.

A fresh verified backup recorded all 76 SQLite tables and 79 Mongo namespaces
with canonical gzip readbacks. The SQLite backup SHA256 was
`03059d937ad84566e1494455b317eb282257b5fa64fc693ae857f95accf1bd7a`;
fresh pre/post hashes were
`bfc1bd9199e3afc5a520a3e17d92c92236e25bb2661f35dd0d510585a5db311c`
and `36e6968055455f25cc6e37cc5526540b0686609fae9c59f23440c9d952154ac5`.
The owned bot stop, lease drain, startup and readiness completed before backend
activation. AF bot PID 2976220 and backend PID 2977455 both passed readiness.
A first backend attempt was rejected by automatic approval review because its
state file still showed bot readiness pending. The rejected command did not
run; the parent supplied the completed readiness proof, corrected that state
record and retried the same action with approval. No workaround was used.

The single signed-out auth smoke returned 302 to Discord's authorize endpoint
without following the redirect. Its independent before/after SQL snapshots had
all 76 counts, raw digests, schema, pools and publications exact, including
unchanged `oauth_states`. No live OAuth login, production Save or Discord test
post occurred.

The completed post capture and binding preceded assessment. The original SQL
comparator returned PASS: all 76 counts, schema, pools and publications matched,
with raw digest differences limited to the permitted participation group
observations and sync settings proof. Sessions remained 207→207. Mongo
namespace and index metadata matched. These are pre/post activation database
observations taken **before code rollback**; no database snapshot after recovery
is claimed here.

Post assessment nevertheless exited 1 with “Human configuration or unknown
document changed”. The redacted diagnostic counted 325 changed identities
flagged by the conservative human/unknown projections. Source-owner assessment
was pending; the diagnostic did not settle which changes were ordinary running
work, unintended release effects or actual human-configuration edits. The
failure remains a failed gate rather than a completed AF release.

Code recovery immediately attempted backend H first, then independently restored
bot G after the full 210-second drain. The initial backend readiness HTTP
assertion failed; its exact HTTP status and cause were not established. Bot
recovery continued and passed readiness. The aggregate recovery command exited
1, and that result remains failed. A later read-only backend recheck passed
without another restart. The parent's subsequent HOST verification confirmed
both recovered revisions and the process identities above, cwd/argv and pidfd
ownership, unchanged environment/drop-ins/frontend, config 200 twice, anonymous
seasons 401 and zero current-invocation journal errors.

Recovery checked three critical public hashes: `index.html`,
`assets/index-IcPNVMwd.js` and `assets/MembersPage-B-aD7kL5.js` matched the
unchanged 240 release. The final 184-asset phase was **not run**, because the
failed assessment had already triggered code rollback. No database restore,
index change, data repair, environment or unrelated configuration change,
Discord/provider test write occurred.

Retained evidence is `.local/239af-release-evidence-114/`, particularly
`parent-assess-post-terminal.json`, `parent-recovery-verified.json`,
`parent-recovery-public-critical-hashes.json`, the metadata-only
`backup/pre/post` capture records and `auth-smoke.json`. The redacted field-pattern
summary is `.local/239af-incident126/pattern-summary.json`; individual identities
and values are excluded. At this checkpoint, the failed release report/completion were to be bound
separately, and AF retry/K release facts were pending. The new dated records
below supersede that pending status; this first failed attempt remains failed.

## November 18, 2026 — 239K shared tag formatter, completed

The latest recorded release boundary is K PR
[#377](https://github.com/SirRuggie/WU_Python/pull/377), merged revision
`a8fb4c524c0b84572fc6e28a955dae3fe6a34ad4`, tag `clash-tag-normalize-1`
(object `7fc9e1ddaaa0a612de786df878cc94519df03327`). Completion was recorded at
01:38 EST on November 18. The parent recorded bot PID 3040275, invocation
`50c8a5c56cd642ff96bb46c335a7a5c0`, and backend PID 3040395, invocation
`ce22d702169c4552bd5859eb3bfc1f64`, both on K. Frontend
`14c5e5acc6551f803ca1ae1837c0a57655719de0` and gateway PID 307279 stayed
unchanged. These are saved boundary observations, not fresh production probes.

K retained the prior AF revision
`47d186440d24ff5ff9f07001acc0b31b37911777` for bot/backend code rollback at
this boundary. That is a dated fallback, not a universal standby; any subsequent
M bot release must verify and retain its then-current K bot revision for rollback.
M has not been released in this record.

The verified backup and pre-capture used the **same immutable capture phase**,
not two independent captures. All 76 SQLite counts, column definitions, schema,
pools, six publication records and raw digests matched exactly. The original
`7b09fc9395b32fcbec230f4d77451b89fdd9398505a74224ffcb3d778bfbccdc`
comparator returned PASS with zero changed rows; sessions were 207→207, with
zero D6 expired-session removals. Main was 23 signups / 23 assigned / 23 kept;
Lazy was 147 / 146 / 131, unchanged before/after. The third number is
`SUM(kept)`, not an independently measured lock-table count.

All 79 Mongo namespace inventories, index definitions and positive staff
projections matched. Other recorded count changes were component state 6→9;
member events 5597→5587 with 21 typed eligible removals and 11 additions;
player clan candidates 1101→1100 with one eligible removal; and world-clock
runs 1674→1673 with three eligible removals and two additions. Other counts
matched. Unknown-owner changes in 20 namespaces were recorded under the
prospective 1107 contract. Eligibility is not evidence of TTL causation, and
projection equality is not an all-row-content claim.

The owned stop and full 210-second lease drain, bot/backend startup and readiness,
one signed-out auth GET, completed post capture/comparison and final public
checks passed. Auth returned 302 to Discord without following the redirect or
sending a Cookie; all 76 raw SQL tables and `oauth_states` remained exact across
that smoke. Current-invocation journals had zero errors. All 184 public assets
matched the unchanged frontend, including:

| Public asset                        | SHA256                                                             |
| ----------------------------------- | ------------------------------------------------------------------ |
| `index.html`                        | `ecd1c27bb1ae9efc1a113e3a39cba1719ef34cd7b45f602bef44bafe91de3d02` |
| `assets/index-IcPNVMwd.js`           | `9de9242751f43718b9c44d8073206d7ad151434ff119d459124ca08553381f4b` |
| `assets/MembersPage-B-aD7kL5.js`     | `3b408733b37cb6d8678af1fc01e30e4c67b746fb37f618d4e616679ddaee2384` |

Shaka entry 1110 at 01:39 EST reported **PASS (runtime)**: bot/backend K process
identities, zero tracebacks in the preceding 25 minutes and config 200.
A live tag lookup and live Discord link command were skipped; no Discord test
post was sent. Shaka cleared M to release next; this is not an M completion.

Source validation reused the exact approved K tree's 8551 backend tests
(134 skipped, 544 subtests) and unchanged frontend 2648 tests/type check/Vite
build. Fresh isolated actual-runtime imports passed for 36 bot and 75 backend
modules. These are source/import evidence, distinct from live startup proof.
No CI checks were reported; no CI pass is claimed. Operations review 191
accepted 157 literal checks; parent-script review 193 and artifact review 196
were STATIC reviews, not independent production process logs. The initial
missing-tag preflight failure and later fetch/retry success remain retained.

Frozen completion: `.local/239k-release-evidence-190/completion.json`, SHA256
`69486f9c46248a44834d31009633fb2a7361e313a3a31a680acb4e17d7f955bb`.
Portable report: `.local/239k-final195/review.html`, SHA256
`32d504410a59588308045d6c924dad8f76f127e23f710cead6c42c51d3580a99`.
Shaka's observations are retained separately in `shaka-smoke-1110.txt` and
`closure-1110.json` under the release evidence directory.

## November 18, 2026 — A1+F store off loop, completed third attempt

AF PR [#376](https://github.com/SirRuggie/WU_Python/pull/376), merged revision
`47d186440d24ff5ff9f07001acc0b31b37911777`, tag
`dashboard-store-off-loop-1` (object
`29651ea0faaa3c1670bff318cfd62219ecdfec88`), completed in the separate 177
release. Shaka's completion smoke was recorded at 00:42 EST on November 18.
The parent recorded bot PID 3030557, invocation
`48299bbe14664ac9bd727d449b926188`, and backend PID 3030749, invocation
`9f3900d47b144a5ba49a0087ff352a90`, both on AF. Frontend 14c5e5ac and
gateway PID 307279 were unchanged. The old G bot/H backend fallback at this
boundary is historical; K's later dated record above supersedes it.

The fresh verified immutable ONLINE SQLite backup was also the pre-capture in
the **same phase**; Mongo's 79 gzip readbacks were sequential, not a transactional
snapshot. All 76 SQL counts, column definitions, schema, pools, six publication
records and staff contents matched. The original comparator returned PASS;
raw digest differences were confined to `participation_group_observations` and
`participation_sync_settings` under the prospective 1098 automatic-content
contract (10 clock rows: nine group observations and one sync-settings row).
Sessions stayed 207→207 with zero D6 removals. Main remained 23 / 23 / 23 and
Lazy 147 / 146 / 131 for signups / assigned / `SUM(kept)`.

The source-derived positive staff projections and namespace/index definitions
matched across all 79 Mongo namespaces. Component state increased 6→9;
member events changed 5608→5598, comprising 21 typed eligible expiry/prune
removals and 11 additions. Other counts matched. Unknown-owner changes were
recorded, not silently treated as staff changes or proof of unchanged runtime
rows. Shaka later reviewed the names in 1109 as runtime bookkeeping with no
further action. These observations establish neither TTL causation nor a
blanket all-row-content guarantee.

The full owned 210-second drain, bot/backend readiness, one signed-out auth 302
(no follow, no Cookie), completed post comparison and all 184 public asset
checks passed; all 76 raw SQL tables and `oauth_states` stayed exact during
auth. Current-invocation journals had zero errors. The three critical public
hashes are the same unchanged frontend hashes listed in K's later record.
Shaka entry 1108 reported **PASS (runtime)** for AF identities, zero tracebacks,
config 200 and anonymous seasons 401. Signed-in Chrome, live OAuth login and
production latency under load were skipped.

The positive 1107 policy was prospective. It did not retroactively pass either
failed AF attempt retained separately. Failed 181 partial report generation and its separate
185 variable correction remain preserved. Final review 186 accepted the saved
artifact STATICALLY, not as independent live or process-log verification.
No operator database restore, data repair or manual index repair was performed.

Frozen accepted completion: `.local/239af-release-evidence-177/completion.json`,
SHA256 `b7dbbd0947bb28da0e1b37974a28af227bd037a3db5b5916fdeff7497bee4b37`.
Portable report: `.local/239af-plain-report185/review.html`, SHA256
`6b0b607108c7fd21cf7e21c92329fc6b34c9d9b8131effe9bdf2ab1438208313`.
Shaka's smoke and closure are retained under the 177 release evidence directory.

## November 17, 2026 — AF second attempt failed; separate recovery verified

Attempt 144 activated the same AF revision after the first failed attempt
retained above. Its completion was recorded at 23:11 EST on November 17
(`2026-11-18T04:11:53.589294+00:00`). It remains **accepted: false**.
The negative human/unknown-projection assessment exited 1; the cause of the
projection changes remains unknown. This is not evidence that staff
configuration was actually edited. All 76 pre/post SQL counts, schema, pools,
six publication records and strict staff content checks passed under the
original comparator. Those database observations preceded code recovery.

Code recovery restored old G bot/H backend. The initial backend readiness HTTP
assertion failed, with exact HTTP status unrecorded and cause unknown.
Independent bot readiness passed; the recovery controller still exited 1.
A later separate read-only check of the same backend passed, followed by a
fresh separate verification of both recovered services. At that saved boundary,
bot PID 3012303, invocation `d50fe3483a7d4f58aa3520c910394453`, ran G revision
`29f9823def09e0d55bb0e7e9a22752ef97515851`; backend PID 3011795,
invocation `678cbdf26a5e42388badc8aa46709149`, ran H revision
`469dafea617498918c2891d203391cd9c93bf688`. The later checks do not retroactively
pass the aggregate recovery command or the failed release.

No after-rollback database snapshot was captured. The full 184-asset final
phase did not run; recovery checked only the three critical public hashes.
No operator database restore, data repair or manual index repair was performed.
Ordinary runtime activity and live Discord delivery were not observed by this
docs update. The later prospective positive 1107 policy is not a retroactive
waiver of 144 or the earlier 114 failure.

Frozen failed completion: `.local/239af-release-evidence-144/completion.json`,
SHA256 `27657ca2bdbe07cf7ce29b9cfc49c595480e06b41812dea13514024fe256b1c2`.
Failed report: `.local/239af-failed-report167/review.html`, SHA256
`1db96369253d3d35c68fbe1a8423cd4b2d69a4a917add2019f4fc8843599e593`.

Across these dated records, immutable SQL snapshots cannot detect deletion
followed by identical reinsertion; Mongo captures are sequential. No UI,
assistive-technology, physical-device, live OAuth, live Discord delivery or
production latency proof is claimed. No production probes were repeated for
this documentation update.

## November 17, 2026 — 239G history retention, completed retry

The recorded boundary after G was frontend
`14c5e5acc6551f803ca1ae1837c0a57655719de0`, backend
`469dafea617498918c2891d203391cd9c93bf688` and bot
`29f9823def09e0d55bb0e7e9a22752ef97515851`. Bot PID 2904052, invocation
`444e30325ee647a79b7d65e4a063f7e9`, ran the clean detached checkout at
`/home/botrunner/wu-bot`. Backend PID 2834333 and gateway PID 307279 were
unchanged. These dated observations supersede the earlier bot boundary below;
AF and K are not included in these completed-release facts.

PR [#375](https://github.com/SirRuggie/WU_Python/pull/375), tag
`dashboard-history-retention-365d-1`, used the full head approved by Shaka entry 1096. The first activation **failed** its strict SQL content comparison: seven
existing `clan_weight_war_lineups` rows changed `captured_at` and
`lineup_json` while their primary keys and row count stayed the same. Their
saved state transitions were `inWar` → `warEnded`. All 76 table counts,
columns, schema, pools and publications still matched. Code rolled back to N
`bd412179c85e177ded40336080c0f38987b4e657`; the two approved G indexes were
retained. No database was restored and no index was dropped.

Shaka entry 1098 established a prospective retry contract: record content changes
in the existing automatic lineup and participation capture tables, while keeping
all 76 counts, schema, pools, publications and human-edited contents strict. The
original comparator was unchanged. This did not make the first attempt pass or
establish the cause of its observed changes. Its frozen completion remains
`accepted: false`, status `FAILED_STRICT_SQL_CONTENT_CODE_ROLLED_BACK`.

The accepted retry used the same tag and retained verified full backup at
`.local/239g-release-evidence/bound-before/capture.json`, including 63 canonical
Mongo archives with verified gzip readbacks. Fresh pre/post SQLite hashes were
`2ae8e74f4c8e52af9317b878ce2e4ebc0e902915da5e681b323b96baa7614d49`
and `7f9698f85ac463e42cf45f518d025e12c60ba10fcc82b4d90ac4fcc95869200f`.
All 76 table counts/columns, schema, pools and publications matched. The actual
unchanged comparator returned PASS. Raw digest changes were limited to
`participation_group_observations` and one `last_checked_at` change in
`participation_sync_settings`, proved by the existing narrow clock rule; no
lineup digest changed in the retry. Main remained 23/23/23 and Lazy
147/146/131 (signups/assigned/kept). Human and unclassified table contents stayed
strict.

Both G indexes were already live before the retry and remained exact afterward:
`dashboard_history_target_time_partial_v1` on `{kind:1,target:1,at:-1}` and
`dashboard_history_at_365d_v1` on `{at:1}` with TTL31536000 seconds, both partial
on `kind: dashboard_history`. The retry did not create them. All 63 namespace
index inventories matched. The history guard recorded 455 total documents,
20 history rows, zero history rows older than 365 days and zero array-valued
history kinds/dates. All kind counts and the 20 history rows' identities and
contents matched; no history row was added or removed and no other kind count
dropped. This does not prove live TTL deletion timing.

Mongo count changes were `component_state` 6→9 and `member_events` 5712→5678.
They were recorded under 1082 without attributing them to G; protected metrics
had no differences. These sequential captures are not a cross-collection
transactional snapshot. The owned bot stop, full 210-second lease drain, fresh
history guard, startup and readiness completed before post checks. The retry
needed no rollback. Current-invocation startup/import/index checks passed,
config returned 200 twice and anonymous seasons returned 401.

All 184 public hashes matched the unchanged 240 frontend. Public `index.html`
SHA256 was
`ecd1c27bb1ae9efc1a113e3a39cba1719ef34cd7b45f602bef44bafe91de3d02`;
entry `assets/index-IcPNVMwd.js` was
`9de9242751f43718b9c44d8073206d7ad151434ff119d459124ca08553381f4b`.
Shaka entry 1100 independently checked bot PID 2904052/HEAD29f, clean journals
and config 200. His own production `listIndexes` check was skipped because his
guard blocked that read; the index conclusion relies on the saved Codex proof.
There was no signed-in browser, phone, AT, live Discord delivery or production
latency check.

The corrected validator passed 53 literal-fixture checks and the independent
reviewer also passed 53. The earlier 47-check validator used saved
production-derived inputs and is **not** synthetic-only proof; that history is
preserved. The report generator's final correction passed 55 synthetic checks
and independent review passed 55. Terra's final artifact review accepted the
full 16 scripts, hashes, input bindings and failure history; it was a static
artifact review, not another production verification.

Frozen first-attempt evidence is
`.local/239g-release-evidence/failed-release-review.html`, SHA256
`58c615a44df95883801d391c42813cff30231aee940a02507a3538594913bae0`,
and `completion.json`, SHA256
`ed15ba7737789fcc3c9afb320898358c8be70b356094511c939014d0fe2ad02b`.
The accepted retry is `.local/239g-release-evidence-1098-retry/release-review.html`,
SHA256 `01050e48836381ed593f2981c8fcef0ff37164c73ddfbc1b693ba2517e2730bd`,
and `completion.json`, SHA256
`ca2b0233cb2a3bda53d9e7750d0aa539de3e424b170b34a9e7f75c9b8d081db4`.
DONE1860 and Shaka1100 close G. Retained N bot code is a historical recovery
asset; any later recovery needs fresh identity checks and a newly scoped code
rollback. Keep the approved G indexes and never restore a database or recreate
N's removed 90-day index to roll back code.

## November 17, 2026 — completed 239I/C/N/H and 240 releases

The recorded boundary after 240 was:

| Layer | Revision | Recorded process |
| --- | --- | --- |
| Frontend | `14c5e5acc6551f803ca1ae1837c0a57655719de0` | Atomic external `current` symlink; gateway PID 307279 unchanged |
| Backend | `469dafea617498918c2891d203391cd9c93bf688` | PID 2834333, invocation `73634f361c3f4548993a0d9f276fb4f8`, cwd `backend/469dafea…` |
| Bot | `bd412179c85e177ded40336080c0f38987b4e657` | PID 2815111, invocation `0ec865d428bd495080ab650fd781510b`, cwd `/home/botrunner/wu-bot` |

At those boundaries the retained code rollback assets were frontend
`8e1b57c2906ba04c9f06af14a2c31078da61e750`, backend
`9b7f6be6a02cb0d58378fe1a6ab6199dbadad21d` and bot
`56ed1f4e76cc86fb5debf8c574cfff64a75aec13`. These are component-specific
historical recovery assets, not a universal standby or instructions to switch
them now. In particular, an N bot-code rollback must not recreate the removed
90-day index; see its scoped restriction below. These earlier facts exclude
the later G boundary above; AF and K remain outside the completed records.

### 240 — Members save-status polling, frontend only

PR [#374](https://github.com/SirRuggie/WU_Python/pull/374), tag
`member-save-status-1`, revision `14c5e5acc6551f803ca1ae1837c0a57655719de0`.
Shaka entry 1092 approved the full source head. Release ran serially after H completed;
the backend, bot, gateway and backend drop-ins were unchanged, with no restart.

The clean tagged build and atomic frontend switch matched all 184 public manifest
hashes. Public `index.html` SHA256:
`ecd1c27bb1ae9efc1a113e3a39cba1719ef34cd7b45f602bef44bafe91de3d02`;
entry `assets/index-IcPNVMwd.js`:
`9de9242751f43718b9c44d8073206d7ad151434ff119d459124ca08553381f4b`;
owning `MembersPage-B-aD7kL5.js`:
`3b408733b37cb6d8678af1fc01e30e4c67b746fb37f618d4e616679ddaee2384`.
Config returned 200, anonymous seasons returned 401, and the release-window backend/bot
journals had no new traceback or import error.

Accepted evidence is `.local/240-release-evidence/bound-before/capture.json`:
verified SQLite backup SHA256
`10124c657efc5cebacfc96655a68a09696aab1bfd42b88b8282287657cca4589`
and 63 Mongo namespace archives with canonical gzip readbacks. It records source
binding during capture to the exact configuration bytes and effective runtime
startup inputs. The earlier unbound `before` backup is retained as history, not
the accepted activation gate. Static operation-guard rework was fixed before
activation; this was not a failed activation or rollback.

Fresh pre/post SQLite hashes were
`cb9d1c2f246c5aaaa15f7b32a62d875350291e6403c66f34327938c6e66dee09`
and `4917ef0a7334e0090ea30afd6ef2abfb1f04c94af4820681547c275f67250a53`.
All 76 table counts/columns, schema, pools and six publication rows matched.
Raw row-digest differences were restricted to the existing committed proof for
ten automatic clock rows; other row content stayed strict. Main remained
23/23/23 and Lazy 147/146/131 (signups/assigned/kept); signups/roster 170,
weights 360, weight history 397 and imported winners 82. All 63 Mongo namespace
counts were recorded: only `member_events` changed 5706→5707. Index metadata and
protected metrics matched. Under Shaka entry 1082 this unrelated collection change was
recorded without attributing its cause to the frontend release. Mongo captures
are sequential, not a cross-collection transactional snapshot.

Source review: 2648 frontend tests/384 files, 17 focused tests plus two independent
stale-response cases, TypeScript, Vite and scoped formatting passed. Backend
tests were skipped under the frontend-only prompt. The six screenshots are
authorized **local fixture** headless captures; Codex did not perform a live
production Save, production headless check, phone-tap or AT audit. Shaka entry 1094
independently checked runtime/public hashes. Separately, Shaka entry 1095 relayed
Ruggie's real live-save result at 21:38 UTC: “confirmed no 404 error”. That owner
confirmation closed 240; it is not a Codex live-write test.

Frozen evidence: `.local/240-release-evidence/completion.json` and
`release-review.html`, report SHA256
`47e0feeec0df5e7ceae5f13fc46f113e2301d60e405aa547eca668f6b808d337`;
`shaka-smoke-1094.txt` and `owner-live-closure-1095.json`. The report retains
initial install/binding failures and operation-review limits. No database
restore, index change, manual Discord post or code rollback occurred.

### 239H — role cache and write rights, backend only

PR [#372](https://github.com/SirRuggie/WU_Python/pull/372), tag
`dashboard-role-cache-1`, revision
`469dafea617498918c2891d203391cd9c93bf688`. Shaka entry 1088 approved the full head;
the normal backend release switch changed the cwd from `backend/9b7f6be6…` and
started PID 2834333. Bot N and frontend 8e were preserved. Shaka entry 1093 runtime smoke
passed; signed-in staff access and live role-removal timing were skipped.

The full 63-namespace verified backup is
`.local/239h-release-evidence/before/capture.json`, SQLite SHA256
`a9f9dcbf19b67a7c6655d3de391edc44933e6cc6b584ebb3e3394cfa0e47f2c2`.
Fresh pre/post hashes were
`37a7ac02952e3ba69270bc0c58c93fa25b50f89fbd654914daa4c38c3a8e6c4e`
and `8e169daa7e76e760711513c01cd4127f0252d33d4dcea4b1d31763994b690c7c`.
All 76 counts, raw row digests, schema, pools and publications matched, with zero
clock changes. All 63 Mongo counts/index metadata and protected metrics matched.
Config 200, anonymous seasons 401 and the new invocation journal passed.

Frozen evidence: `.local/239h-release-evidence/completion.json` and
`release-review.html`, SHA256
`6b926a060255487eeac0eb2f42034dd1a0bac04ea991cd2ad096663d00eb5779`;
`raw-all76-digest-confirmation.json` and `shaka-smoke-1093.txt`. Static rollback
temporary-file rework was corrected before activation. No H rollback or data
restore occurred. Shaka's source-suite run had 8294 passes and one pre-existing
B isolation-test flake; it was not an all-pass run. Builder and independent
Terra runs passed 8295 tests, and the flake was fixed separately in PR373.

### 239N — departed-player retention, bot and scoped index replacement

PR [#368](https://github.com/SirRuggie/WU_Python/pull/368), tag
`player-activity-retention-180d-1`, revision
`bd412179c85e177ded40336080c0f38987b4e657`. Shaka entry 1085 approved the full head;
Ruggie's separate scoped replacement approval is recorded in handoff 1818.

After backup verification and the owned bot stop/lease drain, only the old
`activity_departure_retention` index (`left_at`, TTL7776000, no partial filter)
was dropped. A separate completed receipt validation preceded bot startup.
The normal `ensure_indexes` path created `activity_departed_player_180d`
(`left_at`, TTL15552000, partial filter requiring null/missing `kind`, a string
`tag`, and an existing date-valued `left_at`). Read-only index evidence
confirmed the new specification, old index absence and all other indexes
unchanged. No manual new-index creation, backfill or data repair occurred.

The fresh activity archive SHA256 was
`5b052722d8db58f0015e470fec728555b1d85c2b686b6310f622b989a28f68ad`:
621 documents,596 players,25 history rows,39 players with a `left_at` date and
zero players older than 180 days. Canonical readback and an isolated MongoDB 7
restore matched; production was observed as 8.0.37. All 25 original history IDs
and contents survived; zero documents were added or removed. This does not
prove live TTL deletion timing. One player's existing observer fields changed;
that was recorded without a release-causation claim.

The SQLite backup in `.local/239n-release-evidence/before/capture.json` had
SHA256 `24deec46b37d3ce2884052b40dc0f284c75b3fec785bae676c6cd7a030f7391d`.
All 76 counts/columns, schema, pools and publications matched after release;
ten permitted automatic clock rows changed. The prior C full 63-namespace
backup was retained alongside fresh N counts and the fresh activity archive.
Other Mongo count differences were `component_state` 3→4 and
`member_events` 5730→5709; protected metrics matched. Backend 9b7 and frontend 8e
were unchanged. Bot PID 2815111 started cleanly with no index/startup failure.

Shaka entry 1090 runtime smoke passed; his production `listIndexes` read was skipped
because his guard blocked it, so that part relies on the saved Codex read-only
proof. Frozen evidence: `.local/239n-release-evidence/completion.json` and
`release-review.html`, SHA256
`66e112f0a51a392972663b6831a3e855eeb1395c472f513a4d85e8ba4286866e`.
The prepared, unexecuted recovery could remove **only** the new 180-day index
and restore bot code `56ed1f4e…`. Never recreate the old 90-day index or restore a
database for this code rollback. Static recovery reworks were fixed before the
production index operation; no live Discord delivery test was performed.

### 239C — ticket welcome nonces, bot only

PR [#371](https://github.com/SirRuggie/WU_Python/pull/371), tag
`ticket-welcome-nonce-1`, revision
`56ed1f4e76cc86fb5debf8c574cfff64a75aec13`. Shaka entry 1084 approved the full head;
bot PID 2789304 ran this revision while backend 9b7/frontend 8e stayed unchanged.
Shaka entry 1089 runtime smoke passed. The client nonce/enforce-nonce mapping and
startup were checked; live Discord deduplication was not tested with a post.

Verified backup `.local/239c-release-evidence/before/capture.json`, SQLite
SHA256 `b2415d408236f7bb12d48ec9fe5b81ca197b6fd62e2d43d603ebf287282cabe5`;
63 Mongo archives had gzip readbacks. All 76 SQL counts/columns, schema, pools
and publications matched, with ten permitted automatic clock-row changes.
All 1630 `initial_delivery` receipt states were unchanged. Five top-level ticket
refresh records and `component_state`3→6 changed through unchanged paths and
were recorded under 1082; no unintended changed-diff Mongo effect was found.
Indexes and protected metrics matched. The retained bot-code rollback was 9b7;
it was not executed. No data restore or live Discord test post occurred.

Frozen evidence: `.local/239c-release-evidence/completion.json`,
`shaka-smoke-1089.txt` and `release-review.html`, report SHA256
`f895b9deebeb2de7b673c81c098b7342bd6f09a2c05d7e64203fee0d0ba15105`.

### 239I — image-fetch safety, bot and backend

PR [#370](https://github.com/SirRuggie/WU_Python/pull/370), tag
`image-fetch-safety-1`, revision
`9b7f6be6a02cb0d58378fe1a6ab6199dbadad21d`. The accepted 1082 retry ran bot
PID 2752217 and backend PID 2754332; frontend 8e stayed unchanged. Shaka entry 1083
runtime smoke passed. One authorized public Discord-CDN image fetch passed
real TLS (256×256, 1268 bytes); its first-activation evidence was retained, not
fetched again. No Discord upload/post or signed-in browser check was made.

Verified full backup `.local/239i-release-evidence/before-r1/capture.json`,
SQLite SHA256
`25b6575dcd63c4a59981a40c11bfbef3d1d4bb2d37b2d429f7f7b7d2caadb482`,
included 63 Mongo namespaces with gzip readbacks. Fresh accepted retry pre/post
SQL hashes were
`6e0655b65f019c646b9832d177e4463d970ac0fca6b2fdc89934cfd588671168`
and `df90e5d60cd406a439b951f1154fd1cc96773c1f462062f18cdbc91008a9d9c3`.
All 76 table counts, raw row digests, schema, pools and publications matched;
zero clock changes. Mongo `component_state`2→5 and 153 profile clock-only
changes were recorded, with no added/removed profiles and unchanged protected
metrics. The downloader diff writes no collections;1082's assessment did not
establish a causal explanation for background changes.

The earlier 1080 attempt **failed and rolled back code** because Mongo changes
fell outside its named list. Its frozen failure evidence remains failed.
Shaka entry 1082 replaced that list with the recorded-unrelated-collection rule and
authorized a fresh pre/post retry on the same tag; it did not retroactively pass
the first attempt. Original code rollback assets were bot
`c678cb6367ec1f768320010db8b0c17a239fc933` and backend 8e; no database was
restored. Frozen evidence: `.local/239i-release-evidence/completion.json`,
`shaka-smoke-1083.txt` and `release-review.html`, report SHA256
`203e3ac47b4642146d1695635d7d08c541201c5421b164474a210afa8a7bdb7c`.

Across I/C/N/H, the unchanged frontend 8e public entry was
`assets/index-C-wTAPQ6.js`, SHA256
`11a3c25025abcb0cfc67a4406ad06daffbac12d4ed5d33371611f424b02ef3fc`;
public HTML SHA256
`01466c8c6032b3b247734f8055b419be1742ac600b60df027bfb390590a16982`.
These values describe those successful boundaries, not the later 240 frontend.
All Mongo backups/count captures above are sequential rather than transactional
snapshots; none grants a blanket claim that all live row content stayed fixed.

## War reminder switches — 2026-11-15 (frontend + backend)

- PR [#366](https://github.com/SirRuggie/WU_Python/pull/366), merge commit
  `8e1b57c2906ba04c9f06af14a2c31078da61e750`, local tag
  `war-reminder-switches-366-1` (clean clone
  `/home/ruggie/wu-release-checkouts/war-reminder-switches-366-1`). Built and
  released by Shaka (Claude) on Ruggie's "Shaka build this and release".
- Changes: War reminders overview and editor On/Off switches (instant save),
  shared `rosterUi/Switch` (World clocks uses it), one filter row, editor
  cleanup. Backend: overview rows gain `revision` (Ruggie-approved); two
  validation messages say "Select"/"turn on". No route, schema, data, config,
  secret or systemd change other than the normal release switch.
- Bot not released: its only changed import, `utils/war_reminders.py`, changed
  two strings in `validate()`, which only the web backend calls.
- Checks: clean tagged clone vitest 2631 tests in 383 files; branch full pytest
  8217 passed, 134 skipped; `tools/check_war_reminders.py` pass; family-clans
  layout test pass; independent refuter ACCEPT.
- Frontend `current`: `c678cb63…` → `8e1b57c2…`. Entry `index-C-wTAPQ6.js`.
  All 184 manifest files match on `dash.warriorsunited.cc`.
- Backend `release.conf` `backend/c678cb63…` → `backend/8e1b57c2…` (file diff
  versus the old backend is only the PR's files); PID 2161731 → 2311879;
  `/proc/<pid>/cwd` = new backend; `/api/cwl/config` 200; no tracebacks for the
  new PID in the journal.
- Backup `.local/war-reminder-switches-366-release-20261115T230611Z/before.sqlite3`:
  integrity ok, all 76 tables and schema equal to live, SHA-256
  `6b24de1babac85a4fa314066c799d28f6b08fc89fdb730832f9a24aee6e0f436`. After:
  76 table counts and schema identical; content changed only in the automatic
  tables `participation_sync_settings` and `participation_group_observations`
  (see `release-automatic-fields.md`). Mongo counts not compared.
- Smoke: anonymous HTTP (`/`, `/signup`, `/clans/reminders` 200 with the new
  entry; `/api/cwl/auth/me` 401). Signed-in read only in Ruggie's Chrome:
  25 overview rows, every row has a `revision`, 2 switches (both On), 23 "Set
  up", Filters button present, no Refresh button. No switch selected, no app
  writes, no Discord post.
- Rollback (code only, never restore the DB): write `release.conf` back to
  `backend/c678cb6367ec1f768320010db8b0c17a239fc933`, `systemctl --user
  daemon-reload`, `switch-release.py c678cb6367ec1f768320010db8b0c17a239fc933`,
  `systemctl --user restart wu-cwl-demo-web.service`.

## TH19 emoji — 2026-11-14 (frontend + backend + bot)

- PR [#363](https://github.com/SirRuggie/WU_Python/pull/363), merge commit
  `4d4158bd596b28eb49f2a89c8f89c06e5a687958`, local tag `th19-emoji-363-1`.
  Released by Shaka (Claude) on Ruggie's "Merge and release 363".
- Changes: `utils/emoji.py` adds TH19 (`<:TH_19A:1571025137896005783>`);
  `utils/war_weight.py` `emoji_for` prefers the configured emoji name;
  `web/cwl/src/TownHallIcon.tsx` adds "19"; 2 test files. No route, schema,
  data, config, secret or systemd change. Backend imports `utils.war_weight`
  through `cwl_web/manage_operations.py`, so all three layers were released.
- Checks: clean tagged clone vitest 2601 tests in 381 files; the two changed
  pytest files 20 passed; build via `stage-release.py`. Full backend suite
  not run for this release.
- Frontend `current`: `bb87479f…` → `4d4158bd…`. Entry `index-CIzI7IBQ.js`,
  SHA-256 `3bb28f7eb5b44ab4cee25f77363b5109fd4b8238537f01dc4db90b24514a1203`;
  TownHallIcon is in the entry and contains `1571025137896005783`. All 182
  manifest files match on the origin (127.0.0.1:8766) and on
  `dash.warriorsunited.cc` (`cwl.ruggie.zone` redirects there).
- Backend `release.conf` `b68c09e4…` → `4d4158bd…` (other drop-ins
  byte-identical); PID 1436505 → 1735036; `/proc/<pid>/cwd` = new backend;
  `/api/cwl/config` 200 twice; journal clean.
- Bot: `/home/botrunner/wu-bot` `2c6aa95d…` → `4d4158bd…` (detached, clean,
  requirements unchanged; non-web diff is only the files above). PID 1467543
  → 1735352, InvocationID `e12a646107d0427e9d9b2a96a5d20b56`, NRestarts 0;
  60 extensions loaded (same as before), shard ready, started in about 5 s,
  no errors or tracebacks in the journal.
- Backup `.local/th19-emoji-363-release-20261114T060619Z/before.sqlite3`:
  integrity ok, equal to live, SHA-256
  `6c69c1caf3a467f109082031248962da070635d471e6c4398982d2048087be3a`. All 76
  table counts, Main 23/23/23, Lazy 147/146/131, publication max version 6
  (6 rows, 4 active) and the lineup-rules digest identical before and after.
  Mongo counts not compared (the live bot writes continuously).
- Smoke: anonymous HTTP only (`/`, `/signup`, `/strikes`, `/server/members`
  200 with the new entry; `/api/cwl/auth/me` 401; `/api/cwl/config` 200).
  Signed-in smoke SKIPPED. No app writes, no Discord post.
- Rollback (code only, never restore the DB): write `release.conf` back to
  `backend/b68c09e4aaafcb2c160e0132c5d322ad03b7cbce`, `daemon-reload`,
  `switch-release.py bb87479f79776a2749236d55c5676952fa442129`, restart the
  backend; `sudo -n -u botrunner git -C /home/botrunner/wu-bot checkout
  --detach 2c6aa95d`, then `sudo -n systemctl restart wu-bot.service`.

## Seasons: next month in one select — 2026-11-14 (frontend only)

- PR [#362](https://github.com/SirRuggie/WU_Python/pull/362), merge commit
  `bb87479f79776a2749236d55c5676952fa442129`, local tag
  `seasons-next-month-362-1`. Built by Shaka (Claude); separate reviewer
  REWORK fixed. Merged and released on Ruggie's "merge and release".
- Changes: Seasons "Create <month>", "Finish <month>" (create next month if
  missing, show it to members, optional open signups, off by default) and
  "Lock <month>" (only before the member month). Uses existing endpoints; no
  Python, route, schema or data change.
- Checks: clean tagged clone vitest 2601 tests in 381 files; build via
  `stage-release.py`.
- Frontend `current`: `b68c09e4…` → `bb87479f…`. Entry `index-Brl1gkrn.js`.
  All 181 manifest files match on the origin (127.0.0.1:8766) and on
  `dash.warriorsunited.cc`. Backend not changed or restarted (PID 1436505).
  Bot not changed.
- Backup `.local/seasons-next-month-362-release-20261114T012415Z/before.sqlite3`: integrity ok, equal to live, SHA-256
  `6ed3ea85a8d1f6e302d8583f72b7dd758de7a2288990d4f7cf469eea53c0701f`. All 76 table counts, Main 23/23/23, Lazy 147/146/131,
  publication max version 6 and the lineup-rules digest identical before and
  after.
- Smoke: anonymous HTTP only. Signed-in smoke SKIPPED. No writes; Create,
  Finish and Lock were not selected live.
- Rollback: `switch-release.py b68c09e4aaafcb2c160e0132c5d322ad03b7cbce`.

## /manage "TH weight ranges" label — 2026-11-14 (bot only)

- PR [#360](https://github.com/SirRuggie/WU_Python/pull/360), merge commit
  `2c6aa95d83076bdd4c022c6bdf2dbc467d13745e`, local tag
  `manage-th-weight-360-1`. Merged and released by Shaka (Claude) on Ruggie's
  "Merge and restart".
- Change: Discord `/manage` FWA panel label, title, breadcrumb and permission
  error text "War Weight" → "TH weight ranges"; docs/manage-web-parity.md row.
  Action id `fwa_weight`, stored settings and behaviour unchanged.
- Checks: backend suite in a network-isolated namespace 8208 passed, 132
  skipped, 2 failed (real-Mongo ticket tests that need a network database;
  files not touched). Import check as botrunner passed.
- Bot: `/home/botrunner/wu-bot` `470388ca…` → `2c6aa95d…` (detached, clean,
  fast-forward; requirements unchanged). Other non-web files since `470388ca`
  are `cwl_web/{access_settings,exports,manage_operations,server_management}.py`,
  already released with the dashboard backend `b68c09e4`. PID 1030657 →
  1467543, InvocationID `30e15a512f95415a913d9cb4b80b9bc0`, NRestarts 0; 60
  extensions loaded (same as before), gateway ready, no tracebacks or errors in
  the first minute of the journal.
- Dashboard frontend and backend not changed or restarted.
- Backup `.local/manage-th-weight-360-release-*/before.sqlite3`: integrity ok,
  SHA-256 `0b2a28046a1d338099948aad2bffc4d1845c3ddadf99534dfdae8fe7de000caf`;
  all 76 table counts, Main 23/23/23, Lazy 147/146/131, publication max version
  6 and the lineup-rules digest identical before and after. Mongo counts not
  compared (the live bot writes continuously). No Discord post; `/manage` was
  not opened live.
- Rollback: `sudo -n -u botrunner git -C /home/botrunner/wu-bot checkout
  --detach 470388ca`, then `sudo -n systemctl restart wu-bot.service`.

## UI audit 2, Phases A–F2 — 2026-11-13 (frontend + backend label)

- PR [#358](https://github.com/SirRuggie/WU_Python/pull/358) (contains #352 A,
  #355 B, #354 C, #357 D, #356 E, #353 F1, plus F2), merge commit
  `b68c09e4aaafcb2c160e0132c5d322ad03b7cbce`, local tag `ui-audit-2-358-1`.
  Built by Shaka (Claude) with parallel builders; each phase had a separate
  reviewer (REWORK items fixed). Merged on Ruggie's "Merge it", released on his
  "Release it" in the project thread.
- Backend change: display label only, "War weights" → "TH weight ranges"
  (`cwl_web/manage_operations.py`, `cwl_web/server_management.py`). No key,
  route, schema or data change. Bot not changed.
- Checks: clean tagged clone vitest 2584 tests in 378 files; build via
  `stage-release.py`; backend manage tests 45 passed from the clone; phase E
  branch full pytest 8210 passed, 132 skipped. Release imports verified from
  `backend/b68c09e4…` with the shared virtualenv.
- Backend `release.conf` `16f6badf…` → `b68c09e4…`; restart PID 1117969 →
  1436505; `/proc/<pid>/cwd` = new backend; journal clean.
- Frontend `current`: `075af26f…` → `b68c09e4…`. Entry `index-Bsvm4vzn.js`.
  All 181 manifest files match on the origin (127.0.0.1:8766) and on
  `dash.warriorsunited.cc`.
- Backup `.local/ui-audit-2-release-358-20261113T234555Z/before.sqlite3`:
  integrity ok, equal to live, SHA-256
  `da6eb098eedaf8320119e960a7c400c6d8b4d305b1e5b3a1d5c0c21c39f87db3`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131, publication max version 6
  (6 rows, 4 active) and the lineup-rules digest identical before and after.
- Smoke: anonymous HTTP only (7 routes incl. `?tab=`/`?status=` deep links 200
  with the new entry; `/api/cwl/auth/me` 401; `/api/cwl/config` 200).
  Signed-in browser smoke SKIPPED (Chrome extension not connected). No app
  writes, no Discord post.
- Rollback (both layers): write `release.conf` back to
  `backend/16f6badfe337902704bb5663a6448ad20322ed34`, `daemon-reload`,
  `switch-release.py 075af26f6bb4111008bce40ebefc4ba73bf4d3ab`, restart. Never
  restore the database for a code rollback.

## Browser problem banner: no cancel reports, Dismiss — 2026-11-13 (frontend only)

- PR [#347](https://github.com/SirRuggie/WU_Python/pull/347), merge commit
  `2ff645bbb4605ac76662142eaaa9ca964149f43d`, local tag `banner-dismiss-347-1`.
  Built, merged and released by Shaka (Claude) on Ruggie's "build it fully with
  shaka, merge and release". Independent refuter ACCEPT on head `4847d067`.
- Cause: issue `477da595ac01` was `kind=network_error`. `api()` reported
  requests that a view cancels on purpose and requests that a hidden page drops.
  The banner had no close control.
- Changes: `api.ts` `isExpectedCancel()` (no report for an aborted signal,
  `AbortError` or a hidden page); `issueNotice.ts` banner with a Dismiss button.
  Only `web/cwl/` changed since `7a221f96`. No Python, route, schema or data change.
- Checks: vitest 2531 tests in 368 files (branch and clean tagged clone),
  `tsc -b`, build; backend 8195 passed, 134 skipped (network-isolated namespace).
- Backend not changed or restarted (PID 949466). Bot not changed (PID 871536).
- Frontend `current`: `7a221f96…` → `2ff645bb…`. Entry `index-CsRHakeD.js`,
  SHA-256 `202cec43b1e22f67c2d9b642b5fc73b1475223a4fae653c533be7b87da35d663`.
  All 181 manifest files match on the origin (127.0.0.1:8766). Public
  `cwl.ruggie.zone` serves the same entry on `/`, `/signup`, `/strikes`,
  `/server/members`, `/settings/integrations`; 180 public assets match. Public
  `index.html` differs only by the Cloudflare Web Analytics beacon script.
- Backup `.local/banner-dismiss-347-release-20261113T194621Z/before.sqlite3`:
  integrity ok, equal to live, SHA-256
  `cb693c4865a61e9134f43590e0ea4b180a896920a4de4e6ab5155a8a20ca41d6`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131, publication max version 6
  (6 rows, 4 active) and the lineup-rules digest identical before and after.
  Note: `snap.py` always prints `backup_equal_live: false` because it compares
  after it adds the backup keys; equality was checked separately.
- Smoke: signed-out HTTP only; anonymous `/api/cwl/auth/me` 401. Signed-in
  browser smoke SKIPPED. No app writes, no Discord post.
- Rollback: frontend `switch-release.py
  7a221f96fee18ec1f6057e4c9b7b73874ec47131`. Never restore the database for a
  code rollback.

## UI audit Phases 5 and 6 — 2026-11-13 (frontend only)

- PRs [#338](https://github.com/SirRuggie/WU_Python/pull/338) (Phase 5, merge
  `8077764dd115a8f04654a31694a604e2b7723991`) and
  [#337](https://github.com/SirRuggie/WU_Python/pull/337) (Phase 6, merge
  `a1b8df6e46d6b3cd09048b2f09ab99c0c003aae8`), local tag `ui-audit-5-6-1`.
  Released by Shaka (Claude) on Ruggie's "merge and release 338 337"
  (2026-11-13 17:43 UTC).
- Changes: shared CSS tokens for colors, type, corners and breakpoints
  (Phase 5); the four largest screens split into smaller files (Phase 6).
  Only `web/cwl/` and docs changed since the bot release `32d9c56f`. No Python,
  route, schema or data change.
- Backend not changed or restarted: `backend/523cc293…`, PID 830330, active.
  Bot not changed or restarted (`32d9c56f…`, PID 871536).
- Frontend `current`: `523cc293…` → `a1b8df6e…` (clean tagged clone, `npm ci`,
  `tsc -b` and 2517 tests in 365 files passed before staging). Entry
  `index-u6269ilZ.js`, SHA-256
  `c9f659984de22ca414c735df479801f0e7de5aa71a3120b32b67261094402976`. Served
  `index.html` equals the release file on `/`, `/signup`, `/strikes`,
  `/server/members`, `/settings/integrations`; all 181 manifest files match the
  public site (`/index.html` first returned a stale edge copy; the cache-busted
  and repeat fetches matched).
- Backup `.local/ui-audit-5-6-release-20261113T175329Z/before.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `05f7a1003e0ff2b59426705bce883f1ab4439c939769b7902900b92ef9894604`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Smoke: signed-out HTTP only; anonymous `/api/cwl/auth/me` 401. Browser and
  signed-in smoke SKIPPED. No app writes, no Discord post.
- Rollback: frontend `switch-release.py
  523cc293c823a7fb9ff9e4dd0dc881976708e8e0`. No backend change to roll back.
  Never restore the database for a code rollback.

## Ticket "Link account" control — 2026-11-13 (bot only)

- PR [#340](https://github.com/SirRuggie/WU_Python/pull/340), merge commit
  `32d9c56f3e3fc84b486a4603125f9bfac1a13e8d`, local tag
  `ticket-link-account-340-1`. Merged and released by Shaka (Claude) on
  Ruggie's "you build and deploy the changes" (2026-11-13 16:45 UTC).
- Changes: staff "Link account" control on ticket cards writes ClashPerk links
  (`extensions/commands/tickets/link_account.py`, `player_info.py`,
  `console.py`, `utils/clashperk_link_writes.py`). No schema change, no data
  write. The control was not run live; no Discord post, no ClashPerk write.
- Checks: main merged into the branch (`1dc4d223`, tree equal to the merge
  commit); backend suite 8186 passed, 134 skipped, in a network-isolated
  namespace.
- Bot: `/home/botrunner/wu-bot` `0a061726…` → `32d9c56f…` (detached, clean,
  fast-forward; requirements unchanged). Other bot-side files since `0a061726`
  are not imported by the bot. Import check as botrunner passed. PID 385930 →
  871536, InvocationID `c5aa5b2fdb9341aeb14e6887dd34b986`, NRestarts 0; 60
  extensions loaded (same as before), `extensions.commands.tickets` loaded,
  `[Tickets] thread_runtime_ready configured_fields=6/6 index_errors=0`, no
  tracebacks or errors in the journal.
- Backend not changed or restarted (`backend/523cc293…`, PID 830330; it does
  not import the changed modules). Frontend not changed.
- Backup `.local/ticket-link-account-340-release-20261113T172008Z/before.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `b1e6389a7d056aa4f437d9e925a7669d84a34090151d27001921c488884080b9`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 and the lineup-rules digest identical before and
  after. Mongo counts not compared (the live bot writes continuously).
- Rollback: `sudo -n -u botrunner git -C /home/botrunner/wu-bot checkout
  --detach 0a06172621a542bae2ee0864b5ecf251b298614a`, then `sudo -n systemctl
  restart wu-bot.service`. Never restore the database for a code rollback.

## Non-members can sign in, Base bank members-only — 2026-11-13 (backend and frontend)

- PR [#339](https://github.com/SirRuggie/WU_Python/pull/339), merge commit
  `523cc293c823a7fb9ff9e4dd0dc881976708e8e0`, local tag
  `non-member-sign-in-339-1`. Prompt 238, built and released by Shaka (Claude)
  on Ruggie's "you build and release fully". Independent refuter: REWORK for 2
  missing tests, both added; Base bank gate added on Ruggie's "next".
- Changes: sign-in no longer needs the server; CWL signup save and Base bank
  check membership live (`cwl_web/server_membership.py`); `/auth/me` adds
  `server_member`. No schema change, no data write. See
  `docs/dashboard-sign-in.md`.
- Checks on the merged commit: backend 8168 passed (branch head), frontend 2516
  passed in 365 files and `tsc` in the clean release clone.
- Backend: `release.conf` `backend/22abb00b…` → `backend/523cc293…`; PID
  741607 → 830330, cwd verified, active, ready after 5 s, no journal errors,
  anonymous `/auth/me` and `/bases` 401; other drop-ins byte-identical. Bot not
  changed or restarted.
- Frontend `current`: `22abb00b…` → `523cc293…` (stage-release from the clean
  tagged clone). Entry `index-XXoQk8bM.js`, SHA-256
  `f67142247646c98b366795c75e8e93d9ed0f2709b1105432794028c006b10443`; served
  `index.html` equals the release file on `/`, `/signup`, `/bases`; all 147
  manifest assets match the public site.
- Backup `.local/non-member-sign-in-339-release-20261113T171411Z/before.sqlite3`: integrity ok, equal to live,
  SHA-256 `9c26c4be69ba5afd87edfcd1a68492921ea2f7e1158b13d5ed70345d69676628`.
  All 76 table counts, Main 23/23/23 and Lazy 147/146/131
  (signups/assigned/locks), publication max version 6 and the lineup-rules
  digest identical before and after.
- Signed-in read-only smoke (Ruggie's session): `/auth/me` `server_member`
  true from the live Discord check, no join line on Sign up, `/bases` 200 with
  13 bases. Non-member sign-in on production: SKIPPED (no non-member account).
- Rollback: frontend `switch-release.py
  22abb00bfd4f8106cffbf517a6d0beeb377ad8e7`; backend `release.conf`
  `WorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/22abb00bfd4f8106cffbf517a6d0beeb377ad8e7`,
  daemon-reload, restart. Never restore the database for a code rollback.

## Lazy announcement pings winners — 2026-11-13 (backend and frontend)

- PR [#334](https://github.com/SirRuggie/WU_Python/pull/334), merge commit
  `bc6eb4ca5c02994d3157faeccc749e4dc4b97499`, local tag
  `lazy-ping-winners-334-1`. Released by Shaka (Claude) on Ruggie's "merge
  and release 334" (2026-11-13 16:10 UTC).
- Changes: the renderer (`utils/cwl_bonus_announcement.py`) has no role ping;
  `allowed_mentions.users` is this month's winners per message
  (`ping_users`). The preview (`cwl_web/bonus_announcement.py`) adds
  `ping_count`; the sheet shows it (`LazyAnnouncementSheet.tsx`,
  `lazyAnnouncement.ts`). No route, schema, migration or data change.
- Pre-check: no other release in progress. Last switch was `10aca950` at
  15:40:05 UTC (recorded in draft PR #333); no wu-dashboard file changed in
  the 15 minutes before this release.
- Backend: `release.conf` `backend/7a4abbe6…` → `backend/bc6eb4ca…` (clean
  `git archive`; file list equals the commit tree; only the two changed
  Python files differ from the previous backend; deployed
  `cwl_bonus_announcement.py` has `ping_users` and no `LAZY_CWL_ROLE_ID`;
  imports verified from the release folder). PID 434692 → 659048,
  InvocationID `9e94f2bd60e0492287cee780401b813d`, cwd verified, config 200
  three times, anonymous seasons 401, anonymous
  `lazy-announcement?scope=all&ping=1` 401, unknown route 404, no tracebacks
  from the new PID. `frontend-routing.conf` and `storage-guard.conf`
  byte-identical. Bot (PID 385930) not changed or restarted.
- Build: clean clone at the tag, `npm ci`, `tsc -b` passed, vitest 2510 tests
  in 364 files passed; backend announcement/raffle/Lazy API tests 103 passed;
  checkout clean after; staged with `stage-release.py` (181 files).
- Frontend `current`: `10aca950…` → `bc6eb4ca…` at 2026-11-13 16:31:17 UTC
  (`switch-history.jsonl`). Entry `index-CfePt4H5.js`, SHA-256
  `f1981bd5dbb6adf572b9b66505ebd5f694d2d462191258e487fd743c751e4a35`; feature
  `LazyAnnouncementCard-CfLJoAzi.js` (contains `ping_count`), SHA-256
  `899b99e5cbaf39eadca41dddbc3218fd877f994c4a702b1a2c72aa73770ba165`. Served
  `index.html` (SHA-256
  `d9f95bf04a826febc1b508c1008fd1aa690b900504152c825b07df20e25c928c`) equals
  the release file on `/`, `/cwl/results`, `/cwl/bonuses`, `/cwl/exports`;
  all 147 manifest assets match the public site.
- Backup
  `.local/lazy-ping-winners-334-release-20261113T162719Z/before.sqlite3`
  (SQLite backup API): integrity ok, SHA-256
  `1091a8234588fca8ceff45ddc00eb4f2214478a950216c9f530e8aa744051cb2`; a
  separate read of the backup equals the live snapshot (the script's own
  `backup_equal_live` flag compares after it adds extra keys, so it always
  reads false). All 76 table counts, Main 23/23/23 and Lazy 147/146/131
  (signups/assigned/locks), publication max version 6 (6 rows, 4 active) and
  the lineup-rules digest identical before and after.
- Signed-in smoke SKIPPED. Send was not selected; no Discord post.
- Rollback: backend `release.conf` back to
  `backend/7a4abbe66ad87909544c22f9165fe26cc62936e6`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  10aca95021d01461b9e787d99c67119482ae8140`. Never restore the database for a
  code rollback.

## Log channels category marker — 2026-11-13 (frontend only)

- PR [#332](https://github.com/SirRuggie/WU_Python/pull/332), merge commit
  `10aca95021d01461b9e787d99c67119482ae8140`, local tag
  `log-channels-marker-332-1`. Released by Shaka (Claude) on Ruggie's
  "release 332" (2026-11-13 15:37 UTC).
- Scope: `git diff f3021d21..10aca950` touches only
  `web/cwl/src/ModerationSettings.css` and `docs/release-history.md`. CSS
  only: the Log channels category marker sits inline with its name. No
  Python, route, schema, data, config or systemd change.
- Backend not changed or restarted: `backend/7a4abbe6…`, PID 434692 before
  and after. Bot not changed or restarted.
- Build: clean clone at the tag, `npm ci`, `tsc -b` passed, vitest 2510 tests
  in 364 files passed, checkout clean after; staged with `stage-release.py`
  (181 files).
- Frontend `current`: `f3021d21…` → `10aca950…` at 2026-11-13 15:40:05 UTC
  (`switch-history.jsonl`). Entry `index-DW1S6W9E.js`, SHA-256
  `f8d766adc5b33c0be311e45e3a6055b3b914162c3273158b5bf7886e4aa5c912`; feature
  CSS `ModerationWorkspace-Dvj2w83Z.css`, SHA-256
  `53edc05afce0f9f33096f4276c39ef69353b0c1e74be5d006a91493eca2caf87`, served
  with the new marker rule. Served `index.html` (SHA-256
  `4bd63746a2e86deb95be2a9443d144e382a86dc5063282ce6e21425b72659f98`) equals
  the release file on `/`, `/cwl/results`, `/cwl/moderation`; all 147
  manifest assets match the public site.
- Smoke (read only): config 200 twice, anonymous seasons 401. Signed-in
  smoke SKIPPED. No Save, Send or other write; no Discord post.
- Backup
  `.local/log-channels-marker-332-release-20261113T153757Z/before.sqlite3`
  (SQLite backup API): integrity ok, SHA-256
  `4d5f50a26aa88eda27cee20d552d265c287626b06b5dc57473eac84b95e48ac5`; a
  separate read of the backup equals the live snapshot. All 76 table counts,
  Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks), publication max
  version 6 (6 rows, 4 active) and the lineup-rules digest identical before
  and after.
- Rollback: frontend `switch-release.py
  f3021d21bb54cc218d47fb2db750b8a730aa0e8e`, then verify public hashes. Never
  restore the database for a code rollback.

## Lazy announcement compact row — 2026-11-13 (frontend only)

- PR [#330](https://github.com/SirRuggie/WU_Python/pull/330), merge commit
  `f3021d21bb54cc218d47fb2db750b8a730aa0e8e`, local tag
  `lazy-announcement-330-1`. Released by Shaka (Claude) on Ruggie's "merge and
  release 330" (2026-11-13 14:49 UTC).
- Changes: the Lazy announcement entry is one compact row
  (`LazyAnnouncementCard.tsx`, `LazyAnnouncement.css`). No Python, route,
  schema or data change.
- Backend not changed or restarted: `backend/7a4abbe6…`, PID 434692, active.
  Bot not changed or restarted.
- Frontend `current`: `7a4abbe6…` → `f3021d21…` (clean tagged clone, `npm ci`,
  `tsc -b` and 2510 tests in 364 files passed before staging). Entry
  `index-u0CibkhF.js`, SHA-256
  `8dba029ed5b4ce42fea3dde713e1a7f38d7a52ef956d761776df72ed8f9def55`; feature
  `LazyAnnouncementCard-DCj-doV3.js`, SHA-256
  `cb3f0bbf8abf42c2df84c660a7655bcf592d0b5172e867a550e7fd19c10e8b39`. Served
  `index.html` (SHA-256
  `ffac0f3d3b9f2d0cc4d38998093e7d3736a633a1a0f080fed739f3a85175cb7a`) equals
  the release file on `/`, `/cwl/results`, `/cwl/bonuses`, `/cwl/exports`; all
  147 manifest assets match the public site.
- Backup `.local/lazy-announcement-330-release-20261113T145019Z/before.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `c64a639531302490c05ec18678d5b7b913c82ab3973e383041816b2c6730632e`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, no horizontal overflow, only the expected 401 on
  `/api/cwl/auth/me`, no app writes (only Cloudflare RUM beacons). Signed-in
  smoke SKIPPED. Send was not selected; no Discord post.
- Rollback: frontend `switch-release.py
  7a4abbe66ad87909544c22f9165fe26cc62936e6`. No backend change to roll back.
  Never restore the database for a code rollback.

## FWA Rep 1 per member, no Lazy sit-out — 2026-11-13 (backend and frontend)

- PR [#327](https://github.com/SirRuggie/WU_Python/pull/327), merge commit
  `7a4abbe66ad87909544c22f9165fe26cc62936e6`, local tag
  `fwa-rep-no-sit-out-327-1`. Prompt 237, built and released by Shaka (Claude)
  on Ruggie's "merge and release". Refuter ACCEPT. Rebased on `ab1fd2dd`
  (UI audit 323–326) after that release finished; checks rerun (backend 8145
  passed, frontend 2510 passed).
- Changes: 1 FWA Rep account per linked member (second add refused; existing
  duplicates kept with "Keep 1 account"); a listed Lazy account skips the
  sit-out (`sit_out_exempt`); wording in the help, Settings and chip. No schema
  change, no data write.
- Backend: `release.conf` `backend/8f64316e…` → `backend/7a4abbe6…`; PID
  333211 → 434692, cwd verified, active, ready after 9 s, public config 200,
  anonymous seasons 401, no tracebacks; other drop-ins byte-identical. Bot not
  restarted (does not import the changed modules).
- Frontend `current`: `ab1fd2dd…` → `7a4abbe6…` (clean tagged clone, `npm ci`,
  2510 tests passed before staging). Entry `index-DApwRnP1.js`, SHA-256
  `e1b50e0b361331f37590400a03bf39b5b4fec3a49034e77ce54215f3385cee74`; served
  `index.html` SHA-256
  `49575742ca9aeb370d8318a6fdec8559f0727365c661beccfc982e1ce2509491` equals the
  release file; all 147 manifest assets match the public site.
- Backup `.local/fwa-rep-327-release-20261113T143135Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `e543e51eddf77176a84cd8948a8b2b3b1e2981ecbfac7c5f6a666684d7f8c7f5`. All 76
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, GET only.
  Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/8f64316e6f4fa2100ef9e7a4dafcfe8658a88a0d`, daemon-reload, restart
  `wu-cwl-demo-web`; frontend `switch-release.py
  ab1fd2dd95b1a7015e3c13ac571267de2e2ea379`. Never restore the database for a
  code rollback.

## UI audit phases 1–4 — 2026-11-13 (frontend only)

- PRs [#323](https://github.com/SirRuggie/WU_Python/pull/323),
  [#324](https://github.com/SirRuggie/WU_Python/pull/324),
  [#325](https://github.com/SirRuggie/WU_Python/pull/325) and
  [#326](https://github.com/SirRuggie/WU_Python/pull/326); release commit
  `ab1fd2dd95b1a7015e3c13ac571267de2e2ea379` (merge of #326), local tag
  `ui-audit-1-4-1`. Released by Shaka (Claude) on Ruggie's "Merge and release
  all 4, from what I see it looks good" (2026-11-13 14:19 UTC).
- Scope: `git diff 8f64316e..ab1fd2dd` touches only `web/cwl/` and `docs/`
  (93 files; #321 in the range is docs only). No backend, bot, schema, data,
  config or systemd change. No service restart: backend PID 333211 before and
  after, still on `backend/8f64316e…`.
- Build: clean clone at the tag, `npm ci`, `tsc -b` passed, vitest 2509 tests
  in 364 files passed, checkout clean after; staged with `stage-release.py`
  (181 files).
- Frontend `current`: `8f64316e…` → `ab1fd2dd…` at 2026-11-13 14:24:13 UTC
  (`switch-history.jsonl`). Entry `index-Df6mkzza.js`, SHA-256
  `b71d17959d4b6ba9c6f8bf47a1f5c7b551f982160f4a2d0dea71d775ff73774d`. Served
  `index.html` (SHA-256
  `ddbf9f17e58f4d6ff0c6cb3bd145f4de4984a7a128f16887648c1ea8ba58ae1b`) equals
  the release file; all 147 release asset files match the public site.
  Feature chunks: `StaffOverview-BZLhPlAt.js` (SHA-256
  `4c9874a24b84732d9cbb8f163abe7273ed818829182d4699535867950fd0fdf6`),
  `ModerationWorkspace-CVJm4ap1.js` (SHA-256
  `b7ba36974737501caacf5f32cdcc5327f01038f304736ccdf9e39da4561c19e4`).
- Smoke (read only): config 200 twice, anonymous seasons 401. Served bundles
  contain "Members & moderation" and "Band monitor" (entry), "Activity
  history", "Invites" and "Log channels" (`ModerationWorkspace`); the old
  release contains none of the first two. Public home page loads; the only
  console error is the anonymous 401. No Save, Send or other write; no Discord
  post.
- Signed-in smoke 14:44 UTC (Ruggie signed in; served release was by then
  `7a4abbe6`, which includes `ab1fd2dd`): 7/7 PASS read-only. Sidebar groups,
  Moderation tabs, Band monitor opens directly, Results ends with "Next:
  Exports & history" and has no tab bar, Strikes ⋯ menu items, Members
  buttons; only console error the pre-sign-in 401. Ruggie's phone touch check
  of the ⋯ menus passed 14:55 UTC.
- Backup `.local/ui-audit-1-4-release-20261113T142158Z/dashboard.sqlite3`
  (SQLite backup API, 2,306,048 bytes): integrity ok, equal to live, SHA-256
  `fdef6411caf80aab70472200d2d82282d78b3f6fcd15d0eba1e62ac07ee809b5`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Rollback (frontend only): `python3
  /home/ruggie/.local/share/wu-dashboard/switch-release.py
  8f64316e6f4fa2100ef9e7a4dafcfe8658a88a0d`, then verify public hashes. Never
  restore the database for a code rollback.

## Lazy announcement card and renderer — 2026-11-13 (backend and frontend)

- PR [#322](https://github.com/SirRuggie/WU_Python/pull/322), merge commit
  `8f64316e6f4fa2100ef9e7a4dafcfe8658a88a0d`, local tag
  `lazy-announcement-322-1`. Released by Shaka (Claude) on Ruggie's "Merge and
  release 322" (2026-11-13 04:21 UTC).
- Changes: Participation shows the Lazy announcement card
  (`ParticipationWorkspace.tsx`); the renderer
  (`utils/cwl_bonus_announcement.py`) puts the role ping first and shows names
  in last month's winners. No route, schema, migration or data change.
- Backend: `release.conf` `backend/4ed8462b…` → `backend/8f64316e…` (clean
  `git archive`; imports verified from the release folder). PID 324752 →
  333211, InvocationID `a26748afe0804fca8e78f48693dfd2e3`, cwd verified,
  config 200 three times, anonymous seasons 401, anonymous
  `lazy-announcement?scope=all&ping=0` 401, unknown route 404. No tracebacks
  from the new PID. `frontend-routing.conf` and `storage-guard.conf`
  byte-identical. Bot (PID 3529055) not changed or restarted. Workspace
  fast-forwarded to `8f64316e`.
- Frontend `current`: `4ed8462b…` → `8f64316e…` (clean tagged clone, `npm ci`,
  `tsc -b` and 2483 tests in 357 files passed before staging; backend
  announcement/raffle tests 94 passed). Entry `index-BlbSQ1yr.js`, SHA-256
  `b9e8bf5303ecc57d3943741a878899a5924f18196397494bce20a17c4c1ae442`; feature
  `ParticipationWorkspace-BLelAMct.js`, SHA-256
  `23c7e6936a4ffc0e614471169834d01ec43c98335d9c46cbc998d6d65cba87c3`. Served
  `index.html` (SHA-256
  `30c39d380004235c67ded60dbc89344b9787d7bc8854d8d825c9691577ac1e5c`) equals
  the release file; all 147 release asset files match the public site.
- Backup `.local/lazy-announcement-322-release-20261113T042413Z/dashboard.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `f46db71da22e782780f46f5dbafa09b98b11ce9a5c5c5db46c103d2583663188`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Signed-in smoke SKIPPED. Send was not selected; no Discord post.
- Rollback: backend `release.conf` back to
  `backend/4ed8462be26c82f88e0a8930328166501136dd6a`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  4ed8462be26c82f88e0a8930328166501136dd6a`. Never restore the database for a
  code rollback.

## Lazy bonus announcement — 2026-11-13 (backend and frontend)

- PR [#320](https://github.com/SirRuggie/WU_Python/pull/320), merge commit
  `4ed8462be26c82f88e0a8930328166501136dd6a`, local tag
  `lazy-announcement-320-1`. Released by Shaka (Claude) on Ruggie's "Merge and
  release 320" (2026-11-13 04:06 UTC).
- Changes: staff send the Lazy bonus announcement to a channel from Results &
  bonuses (new `GET/POST /api/cwl/seasons/{id}/bonus-raffle/lazy-announcement`,
  `DiscordTransport.send_components`). No schema change, no migration, no data
  write during the release.
- Backend: `release.conf` `backend/e6477bd9…` → `backend/4ed8462b…` (clean
  `git archive`; imports verified from the release folder). PID 146074 →
  324752, InvocationID `28f6864421f347418dde523992c0d4d7`, cwd verified,
  config 200 three times, anonymous seasons 401, anonymous
  `lazy-announcement?scope=all&ping=0` 401 (route exists; unknown route 404).
  No tracebacks; Clash `accessDenied` lines also occur before the release.
  `frontend-routing.conf` and `storage-guard.conf` byte-identical. Bot
  (PID 3529055) not changed or restarted: it imports none of the changed
  modules. Workspace fast-forwarded to `4ed8462b`.
- Frontend `current`: `2e041c4d…` → `4ed8462b…` (clean tagged clone, `tsc -b`
  and 2481 tests in 356 files passed before staging). Entry
  `index-CeQw4APr.js`, SHA-256
  `b538ff920ccc7e5b3b085cfc29e22b8844be90744079fb890fe53223e9f4aa86`; feature
  `BonusWorkspace-CRtibwIa.js`, SHA-256
  `04b8b60efd2f16a1a579e6e55d9571b9b793fc4140c80040a59e6eade7e66512`. Served
  `index.html` (SHA-256
  `a85b4d23057b662537f21b182c927f37911a030473a605ce46846ad604239d52`) equals
  the release file; all 147 release asset files match the public site.
- Backup `.local/lazy-announcement-320-release-20261113T040738Z/dashboard.sqlite3`
  (SQLite backup API): integrity ok, equal to live, SHA-256
  `e5132ec202bfbf2be39995dd222029ea8f7816ab384d22b9cb0a8bdd250ff5b2`. All 76
  table counts, Main 23/23/23 and Lazy 147/146/131 (signups/assigned/locks),
  publication max version 6 (6 rows, 4 active) and the lineup-rules digest
  identical before and after.
- Signed-in smoke SKIPPED. Send was not selected; no Discord post.
- Rollback: backend `release.conf` back to
  `backend/e6477bd9b599461aa7499ecb9ce84fa9219bbe51`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  2e041c4d7417d5e8f55854b66525e9e4b8f24752`. Never restore the database for a
  code rollback.

## November 12, 2026 —235 Settings menu retry completed

PR [#319](https://github.com/SirRuggie/WU_Python/pull/319), tag
`settings-collapsible-retry-1`, frontend
`2e041c4d7417d5e8f55854b66525e9e4b8f24752`. Shaka entry 1056 approved source
`59cd1978f19d845a0dce49d8c9ef58d81d90a677`;1058 authorized one fresh
release retry using the already staged 181 files, without a rebuild, new tag or
source change. Shaka entry 1059 runtime smoke passed. Shaka entry 1060 separately recorded
Ruggie's “Pass” after the last FWA Rep account ⋯ phone check (normal tap and a
small slide), closing 235 without rollback. That is owner physical-phone proof,
separate from Codex's native mouse smoke.

The opening-pointer rule applies only to menus inside an ActionPanel portal:
record the trigger's opening pointer, ignore a menu-item pointer-up from that
same opening pointer, and clear the guard on a new item press, cancellation,
close or unmount. It uses no timers. Menus outside the sheet retain their
behavior, and Remove still requires its confirmation. The first and last menus
stayed visible inside the native dialog at 360×800 and 1440×1000, with no
unexpected Remove confirmation, overflow or console error. No item selection,
Save, Add, Remove, CheckClash or Refresh was submitted by Codex in this smoke.

All 181 public hashes matched. HTML SHA256:
`bd0343da9daf086506f3c42c0486668741aeb0893192e899ffefc1723b0d11fc`;
entry `index-CCwDSXcv.js`:
`a5d41fc79709566a0319ecc2d40a99bfe6646d4f5c20610729cf41603dfa0925`;
`ResultsSettingsSheet-DVe7cwzW.js`:
`318de889d4146d5289e5057337dc023004c5ee48e7be928d53ea48e7bd16345b`;
`ActionMenu-iCobXhPB.js`:
`82da4fcce2cac2b36f5b0c681b8a83ea7f309436e3e342fc36c50699a83668dc`.

Accepted retry evidence is
`.local/settings-collapsible-retry-release-evidence-235-r2/completion.json`.
The fresh before/after SQLite backups had SHA256
`fa20926597ccdbe638cd9739b860972396d0c88141e63fe1899d54eb50c46bfa`
and `cb49de07029ebcae2299b80d9daff426d6015125bec6fa598f4b4623377986a0`.
Integrity/readback, all 76 table counts **and raw row digests**, schema, pools
and six publication versions matched; the unchanged committed clock comparator
reported zero changed rows. Main 23/23/23 and Lazy 147/146/131
(signups/assigned/kept), imported winners 82 and Rep accounts 8 were retained.
Two sequential canonical Mongo checkpoint readbacks matched their own SQL
phases; this was not a cross-phase transactional snapshot.

Backend PID 146074 stayed on
`e6477bd9b599461aa7499ecb9ce84fa9219bbe51`; bot PID 3529055 stayed on
`0a06172621a542bae2ee0864b5ecf251b298614a`. Gateway 307279, invocation IDs,
drop-ins and environment-file hashes were unchanged, with no service restart,
configuration change, database restore or manual Discord write. Config 200 and
anonymous seasons 401 passed. The retained frontend rollback at this boundary
was 236 `6bb0f41a95ff1c6c17cbeb0ed8259c6c44aeb5a2`; it is historical and
requires fresh state verification before any future use.

The first PR319 activation **failed and rolled back**: its post command resolved
the venv Python symlink to a base interpreter, and the `bson` import failed
before comparing inputs. A later correct recovery comparison did not
retroactively accept that attempt. Its separate failed completion/report remain
frozen under `.local/settings-collapsible-retry-release-evidence-235/`.
The accepted 1058 retry used the exact lexical project-venv command, proved that
command against saved recovery inputs before switching, and took fresh backup,
native receipt/binding and post evidence. Earlier 235 failure/revert history also
remains historical; this record covers the accepted fresh retry only.

Frozen accepted report:
`.local/settings-collapsible-retry-release-evidence-235-r2/release-review.html`,
SHA256 `37c105f3792930190607224f9296a21e96bbe67972b67e5c9c231660a93b0120`.
It retains 56 original JPEGs (historical fixture/failed-attempt and eight fresh
retry captures), full operation scripts and failure history. Existing Funnies
upstream 404/stale warning was observed before Settings; no causal claim or
provider diagnostic was made. No all-pages, AT or live Discord delivery claim.

## November 12, 2026 —232/233 completed (Shaka1041/1042)

These dated records supersede the older current/standby labels below. Recorded
frontend: `3f9792e7489118db1b07b6d12e63780e39e6bbf1` (233); backend:
`e6477bd9b599461aa7499ecb9ce84fa9219bbe51` (232); bot checkout:
`0a06172621a542bae2ee0864b5ecf251b298614a`. These are retained release facts,
not fresh live probes or permission to rerun completed release tools.

- **232**, PR313, tag `exports-excel-1`, FE/BE `e6477bd9…`: verified backup
  `.local/exports-excel-release-evidence-232-1037/pre-stage/.local/discord-links-defaults-1-backup-20261112T211057Z/dashboard.sqlite3`,
  SHA256 `ebd213bee483f0e76595a2ff4483006c9946f53a3d5c122cdf3de717fa21e813`.
  All182 public hashes matched; index SHA256
  `c33e0a4ef07c85de38129f36e946a62b55180535f8d9a2e6bfaa4a3d78849f72`,
  `index-vW-gTMbx.js` SHA256
  `ace397d5710963bcd524148721145dc5c772ab5d77185f5dd03b7fae553c7688`.
  Backend normal switch/restart PID4059855→146074, InvocationID
  `982912e2ee254ade929bcc8f1aa821b7`; bot3529055/gateway307279 unchanged.
  Native read-only Exports closed/open at360/1440, no downloads/writes; separate
  receipt/validator/post each exit0. Shaka1041 runtime SMOKE PASS.
- **233**, PR314, tag `season-picker-labels-1`, frontend `3f9792e7…`: plain
  documented stage/switch after fresh backup
  `.local/season-picker-labels-release-evidence-233/plain-before/.local/discord-links-defaults-1-backup-20261112T212002Z/dashboard.sqlite3`,
  SHA256 `b4560dbeb56b95831ead88b3798d9d516ea3a5a83048b316d4f6a76eea65bfcf`.
  All180 public hashes matched; index SHA256
  `07a4a5b4311390bfe0b941e1148e96961887f9ec609b41b3cd12d484e1199876`,
  `index-IAlUYglT.js` SHA256
  `b1ccc6e89830ea0963576ea019d6a0a00c17924f5ac21d693bf11cea95683f6d`.
  Backend232 PID146074, bot3529055, gateway and configuration unchanged; no
  backend restart. Parent native Roster/Results/Exports and range checks at360/1440
  were read only. Results native OS popup visual was skipped; AX/DOM option
  proof retained. Shaka1042 runtime SMOKE PASS, signed-in UI SKIPPED by Shaka.

Both releases: all76 table counts/schema/raw digests, Main23/23/23 and
Lazy147/146/131 (signups/assigned/locks), imported winners82 and six publication
versions36/473/475/476/544/597 exact.232 four unchanged committed comparison
proofs and233 one proof each have changed_rows0. Sequential Mongo readbacks
matched their own SQL phases; no cross-phase transactional snapshot claim.
Evidence: private232 `release-done.json`/`done-summary.json` and233
`plain-done.json`/`plain-counts-proof.json`, with self-contained release reports.
The233 escaped-test incident was closed with production SQLite read **unknown**;
immediate parent runtime/public verification and final232 raw data were exact.
Per1041 the private233 coordinator/tests were deleted, not repaired or rerun.
No live workbook/Discord/AT/device/all-pages claim.230–233 closed by1042.

## Historical November 2 standby boundary (Shaka smoke 466)

At that boundary, `signup-reminders-ack-1`, commit
`e4f9574ca6243fa4a6c3bf33c70acfb662c0f61f`, was the verified frontend,
backend and bot standby after read-only smoke on November 2. See
[`signup-reminders-ack-1-release.md`](signup-reminders-ack-1-release.md)
for its runtime, hashes, backups and testing limits. Its own recorded rollback
was bot `343d961`, backend `e91982d` and frontend `c55c7f0`. These retained
facts are superseded by later dated release boundaries above; neither this
commit nor those older snapshots are an assertion about the currently running
deployment.

A future bot rollback still needs a newly scoped, reviewed coordinator, actual
runtime verification, the full 210-second inactive lease drain, import/readiness
checks and a recorded war-fetch gap. A bare reset/restart is insufficient.
Preserve retained assets and verify served hashes; never replay a completed
activation coordinator, restore data to roll back code or reverse approved data
corrections.

## Historical deployed snapshot (Claude smoke 131)

`no-war-strikes-1`: frontend, backend and bot at `73eda11a1e883b711bc40494f023b4d87efd5a6b`.
Read-only smoke passed. Previous dashboard code: `cb0052dc93cc30b127e2cbe5006a06c149c43671`;
previous bot: `c9b4ac0f5ca7f64a6fc329d06dde419af403ab46`.
Use the guarded rollback in `docs/dashboard-backend-releases.md`; do not reverse
approved NO WAR corrections or restore databases for a code rollback.

## Dated production and rollback records

  - Latest recorded frontend/backend/bot at Claude smoke 98: `moderation-logs-1` / `c494022e924994435496c3e4f0722eb781460380`, public hashes and runtime checks passed. Bot shipped first, then backend readiness, then frontend. Guarded rollback targets: frontend `a8031084eed09ee89b8063828d4bc2c5d40cc628`, backend `23235ccf2671dfe5675f0bc98d38ab11a011ab09`, bot `b517afd46ecfa9cc08488798eba53393ed5b649f`. Follow [moderation rollback](dashboard-backend-releases.md#guarded-moderation-rollback); any staff inheritance save requires a settings recheck before old-bot downgrade. Never restore data.
  - Historical rollback snapshot: `/home/ruggie/.local/share/wu-dashboard/releases/snapshot-20261027T171555Z/`.
  - Weight-range rollback restores frontend/backend to `b517afd` with the bot unchanged. Trigger-delete rollback restores all three to `6a2f8d7`. Follow the [guarded manual procedure](dashboard-backend-releases.md#guarded-manual-rollback-for-trigger-delete-and-weight-range); a later frontend release must be rolled back first. Never restore databases for code rollback.

## Infractions in player Details — 2026-11-12 (frontend only)

- PR [#309](https://github.com/SirRuggie/WU_Python/pull/309), merge commit
  `e947b72399193b3d542acdf522ef0ec459f5c0da`, local tag `infractions-309-1`.
  Built and released by Shaka (Claude) on Ruggie's "release 309". Refuter
  ACCEPT on `cdcfb5d5`; the notes-lock fix `37073477` followed (2368 tests,
  `tsc -b`, fixture browser check).
- Changes: Lazy infractions (Missed sync, Lingering, Left family, staff
  exception) in the player Details panel with one Save for notes and
  infractions; ⋯ "Infractions" and flag chips on step cards; staff notes are
  no longer locked by their own open Details sheet.
- No Python changed. Backend `backend/ea46425a…` (PID 3671110) and bot not
  changed or restarted.
- Frontend `current`: `ea46425a…` → `e947b723…` (clean tagged clone, 2368
  tests in 348 files passed before staging). Entry `index-CA-3Aok5.js`,
  SHA-256 `a6c82c98910e84212e16fedddf1fa01e6a5feac9b03d56166d678d4d22f1a81b`;
  served `index.html` SHA-256
  `41b9fb4c67c9c29a1581a5fcbfcc6bb62a2a7007ba7163ff4e8cefc76cf54aab` equals the
  release file; all 148 manifest assets match the public site.
- Backup `.local/infractions-309-release-20261112T153438Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `c3dc513bd9535e287441a83c8661966f37db8b0f1582dbc241230c790241bd21`. All 75
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, app requests
  GET only. Signed-in smoke SKIPPED.
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py
  ea46425a44eeb3327e12efe7748da7e649fad7a1`. Never restore the database for a
  code rollback.

## Clan Rep picker for FWA Rep accounts — 2026-11-12 (backend and frontend)

- PR [#306](https://github.com/SirRuggie/WU_Python/pull/306), merge commit
  `ea46425a44eeb3327e12efe7748da7e649fad7a1`, local tag
  `clan-rep-picker-306-1`. Built and released by Shaka (Claude) on Ruggie's
  "merge and release". Refuter ACCEPT; its 2 should-fixes applied in `14e6930d`.
- Changes: read-only `GET .../bonus-raffle/clan-rep-members` (FWA Clan Rep role
  `769130325460254740`, editor access); "Find Clan Rep (x2 odds)" picker in FWA
  Rep accounts with "Add for x2". No schema change.
- Backend: `release.conf` `backend/eccff038…` → `backend/ea46425a…`; PID
  3619459 → 3671110, cwd verified, active, ready after 8 s, public config 200,
  anonymous seasons and clan-rep-members 401, no tracebacks; other drop-ins
  byte-identical. Bot not restarted (does not import the changed modules).
- Frontend `current`: `eccff038…` → `ea46425a…` (clean tagged clone, `npm ci`,
  2338 tests passed before staging). Entry `index-BdiAtLud.js`, SHA-256
  `f5a84cd711efe2daf06774735395296df4e05654cb13fefed49111cef2508c2d`; served
  `index.html` SHA-256
  `bef986e9271d2377718a16b28866f6b2b8f3c20cc11ddce264875e0ccd436aea` equals the
  release file; all 149 manifest assets match the public site.
- Backup `.local/clan-rep-306-release-20261112T023546Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `105f22d92b48873ef7dfffbe717200519092e19812f2c968354e2c13b00c88b9`. All 75
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, GET only.
  Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/eccff03812d9e94580cfc23ea3283a7846f87e03`, daemon-reload, restart
  `wu-cwl-demo-web`; frontend `switch-release.py
  eccff03812d9e94580cfc23ea3283a7846f87e03`. Never restore the database for a
  code rollback.

## FWA Rep accounts for Lazy x2 odds — 2026-11-12 (backend and frontend)

- PR [#304](https://github.com/SirRuggie/WU_Python/pull/304), merge commit
  `eccff03812d9e94580cfc23ea3283a7846f87e03`, local tag `fwa-rep-304-1`.
  Built and released by Shaka (Claude) on Ruggie's "Merge and release".
  Refuter ACCEPT on `9f03c9b8`.
- Changes: Lazy x2 raffle odds come from one family-wide FWA Rep account list
  (Settings sheet), not the Discord role. New additive tables
  `bonus_raffle_rep_accounts` and `bonus_raffle_rep_account_audit`; the old role
  tables stay unread. Lazy draws use `rules_version` 3. The list starts empty;
  no data was written.
- Backend: `release.conf` `backend/ab2e217b…` → `backend/eccff038…`; PID
  3574547 → 3619459, cwd verified, active, local and public config 200,
  anonymous seasons, bonus-status and rep-accounts 401, no tracebacks. Other
  drop-ins byte-identical. The bot imports neither changed module, so it was
  not restarted.
- Frontend `current`: `ab2e217b…` → `eccff038…` (clean tagged clone, `npm ci`,
  2337 tests in 344 files passed before staging). Entry `index-CBlehv8O.js`,
  SHA-256 `c3a9fe428a132291ffc77d9303bdf7bb4ed802f1671341aec505cf1880983373`;
  served `index.html` SHA-256
  `de1d95b9bcf8d030ca970945caf5c2155d47c52c6d0a46f99ad4dc9345a5d90b` equals the
  release file; all 149 manifest assets match the public site.
- Backup `.local/fwa-rep-304-release-20261112T011449Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `39ea13dfd603d6673d5f4f36343f1e69a5e5580635210f4761aa28396b28db52`. All 73
  existing table counts identical after; 2 new tables, both empty.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, app requests
  GET only. Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/ab2e217b9e5ac6ece40cb6bb5e233625a178331a`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  ab2e217b9e5ac6ece40cb6bb5e233625a178331a`. The new tables stay; never restore
  the database for a code rollback.

## Clan dropdown and Lazy-only sit-out — 2026-11-11 (backend and frontend)

- PR [#302](https://github.com/SirRuggie/WU_Python/pull/302), merge commit
  `ab2e217b9e5ac6ece40cb6bb5e233625a178331a`, local tag
  `clan-dropdown-302-1`. Built and released by Shaka (Claude) on Ruggie's
  "Release 302". Refuter ACCEPT on `0ac81f82`; a copy/CSS polish commit
  followed (2334 frontend tests rerun).
- Changes: one "Hosting clan" dropdown with state in each option (clan cards
  and "Find a clan" removed); Find a player and Sort on one row; overview gets
  the shared `roster-ui` tokens; the Lazy 3-month sit-out counts only earlier
  Lazy bonuses (Ruggie: "per pool").
- Backend: `release.conf` `backend/0a061726…` → `backend/ab2e217b…`; PID
  3529151 → 3574547, cwd verified, active, config 200, anonymous seasons 401,
  no tracebacks. Python diff limited to `utils/cwl_bonus_raffle*.py` and its
  test; the bot imports neither, so it was not restarted (`wu-bot` active).
- Frontend `current`: `0a061726…` → `ab2e217b…` (clean tagged clone, 2334
  tests in 344 files and 75 Lazy bonus backend tests passed before staging).
  Entry `index-DVjQeDFr.js`, SHA-256
  `e17c2c975eee7b7a36da3974db7bca3aeb9f29c99a2505b6ae1075576f814500`; served
  `index.html` SHA-256
  `617acf39966b8fec9055e45929c3d72ab30f7b189d4d17dd89fcc1e3193e9d36` equals the
  release file; all 149 manifest assets match the public site.
- Backup `.local/clan-dropdown-302-release-20261111T223740Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `a607fee98edbed2a0ad6bc6f5469e8254877f3045243cc8b7a116acfefd5b819`. All 73
  table counts identical before and after.
- Signed-out smoke at 360 px on `/cwl/results`, `/cwl/bonuses`,
  `/cwl/exports`: new entry, only the expected 401, no overflow, app requests
  GET only. Signed-in smoke SKIPPED.
- Rollback: backend `release.conf` back to
  `backend/0a06172621a542bae2ee0864b5ecf251b298614a`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  0a06172621a542bae2ee0864b5ecf251b298614a`. Never restore the database for a
  code rollback.

## Results & bonuses one flow — 2026-11-11 (frontend only)

- PR [#299](https://github.com/SirRuggie/WU_Python/pull/299), merge commit
  `11959254eedfef916e2a136e5df9370a3890a3c8`, local tag
  `results-bonuses-229-1`. Built and released by Shaka (Claude) on Ruggie's
  "release 229". Final refuter verdict ACCEPT on head `56c82382`.
- The diff from the live `7771de45` (plus docs-only `afbf2472`) touches only
  `web/cwl/src` and docs. Backend (`backend/8e800f7a…`, PID 3222929) and bot
  were not changed or restarted.
- Frontend `current`: `7771de45…` → `11959254…` at about 2026-11-11T20:38Z,
  through `stage-release.py` (clean tagged clone, `npm ci`, 2331 tests in 344
  files passed before staging) and `switch-release.py`.
- Public entry `index-DKmp4ptE.js`, SHA-256
  `45224e61561c467832ac486a48dc5052d038805bf8121b32c15c62b2078c181f`; served
  `index.html` SHA-256
  `d601404d9c24ff82820e10a0fc78b1e2e5a0286ce39590fd4a73a35a8a6ddefb` equals the
  release file. All 149 manifest assets fetched from the public site match.
  `/api/cwl/config` 200; anonymous `/api/cwl/seasons` and `bonus-status` 401.
- SQLite online backup
  `.local/results-bonuses-229-release-20261111T203343Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `a41ba2ed3c4ae729e2ee50b02ced62054f370653ec82e4f3921eaf26882ed606`. All 73
  table counts identical before and after.
- Signed-out smoke at 360 px: `/cwl/results`, `/cwl/bonuses` and
  `/cwl/exports` load the new entry; only console error is the expected 401;
  no horizontal overflow; app requests GET only. Signed-in smoke SKIPPED
  (built-in browser signed out).
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py
  7771de450d0a8b6400db1f02411021dbaab25cae`. Never restore the database for a
  code rollback.

## Shared player cards on Bonus medals and Exports — 2026-11-11 (frontend only)

- PR [#297](https://github.com/SirRuggie/WU_Python/pull/297), merge commit
  `7771de450d0a8b6400db1f02411021dbaab25cae`, local tag
  `bonus-exports-cards-297-1`. Released by Shaka (Claude) on Ruggie's
  "Release 297".
- The diff from the live `8e800f7a` touches only `web/cwl/src` and docs.
  Backend (`backend/8e800f7a…`, PID 3222929) and bot were not changed or
  restarted; gateway PID 307279 unchanged.
- Frontend `current`: `8e800f7a…` → `7771de45…` at 2026-11-11T18:15:20Z,
  through `stage-release.py` (clean tagged clone, `npm ci`, 2256 tests in 339
  files passed; `tsc -b` and build ran in the helper) and `switch-release.py`.
- Public entry `index-BbWuEoxV.js`, SHA-256
  `413d79834735d44a43819785e2ad7d7e237cd3c687447e23b21319d499ab2327`;
  `index.html` SHA-256
  `818c69d32ed93b264b083ad04704fcb911f1872cd56492f4f055154cfcc2b10c` equals
  the served file. Index and 13 affected assets (BonusWorkspace,
  ExportWorkspace, ParticipationWorkspace, AccountCard, PlayerCardMeta,
  exportPreview JS/CSS) match the manifest. `/api/cwl/config` 200, anonymous
  `/api/cwl/seasons` and `bonus-status` 401, no tracebacks.
- SQLite online backup
  `.local/bonus-exports-cards-297-release-20261111T181331Z/dashboard.sqlite3`:
  integrity ok, equal to live, SHA-256
  `c83842c890a8a9c2b66d94bf4bce063b4d75f599baab2f88f08306ef3efb3fcd`.
  Season 1: lazy 147 signups / 146 assigned / 131 locks, main 23 / 23 / 23,
  publication version 6, roster revision 621. All 73 table counts identical
  before and after.
- Signed-out smoke: `/cwl/bonuses`, `/cwl/exports` and `/cwl/results` load
  the new entry; only console error is the expected 401 on `auth/me`; GETs
  only. Signed-in smoke by Shaka SKIPPED (built-in browser signed out).
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py
  8e800f7a50b5ee54ec3c8b5058eae7b79095485b`. Never restore the database for a
  code rollback.

## Did not join release — 2026-11-11 (backend and frontend)

- PR [#295](https://github.com/SirRuggie/WU_Python/pull/295), merge commit
  `8e800f7a50b5ee54ec3c8b5058eae7b79095485b`, local tag `did-not-join-295-1`.
  Built and released by Shaka (Claude) on Ruggie's decisions in the thread
  "CWL results are incomplete"; merge on Ruggie's "merge it". Independent
  refuter: REWORK (bonus rules not gated on a finished group) → ACCEPT on head
  `256a96b`.
- Changes: Did not join (finished CWL group, not in league-group or war
  rosters), Filler and Not assigned outcomes; Did not join never counts as
  incomplete and is excluded from Main and Lazy draws without blocking; "Add
  strike" ⋯ item only opens Strikes; Main "Resolve incomplete" links to Results.
- Backend: `release.conf` `backend/d225e33d…` → `backend/8e800f7a…`; PID
  3100542 → 3222929, cwd verified, config 200, anonymous seasons 401, no
  tracebacks. Bot unchanged and not restarted (it imports none of the changed
  modules); workspace fast-forwarded.
- Frontend `current`: `d225e33d…` → `8e800f7a…` (clean tagged clone, 2248 tests
  and `tsc -b` passed). Entry `index-BEbs58hr.js`; served `index.html` equals
  the release file; 9 affected assets match.
- Backup `.local/did-not-join-295-release-20261111T171652Z/dashboard.sqlite3`: integrity ok, equal to live. All 73 table
  counts identical before and after.
- Signed-in smoke by Shaka SKIPPED (the browser was not signed in).
- Rollback: backend `release.conf` back to
  `backend/d225e33d14a357e566d4caa35f4ad1f0c9383b29`, then daemon-reload and
  restart `wu-cwl-demo-web`; frontend `switch-release.py
  d225e33d14a357e566d4caa35f4ad1f0c9383b29`. Never restore the database for a
  code rollback.

## Read-only results release — 2026-11-11 (backend and frontend)

- PR [#293](https://github.com/SirRuggie/WU_Python/pull/293), merge commit
  `d225e33d14a357e566d4caa35f4ad1f0c9383b29`, local tag
  `readonly-results-293-1`. Built and released by Shaka (Claude) on Ruggie's
  decisions in the thread "Audit bonus medals pages". Head `f5a8bdb` ACCEPTED
  after one REWORK round (card body mouse click, partial-results label).
- Changes: attacks and stars are read only (save route returns 400 for changes;
  notes still save); a logged bonus review reason covers never-captured Lazy
  results; the whole Results card opens a read-only Details panel; shared ⋯ menu
  with DM and Details; amber "Partial results" label.
- Backend: `release.conf` `backend/965c3f74…` → `backend/d225e33d…`; PID
  3051555 → 3100542, cwd verified, config 200, anonymous seasons 401, no
  tracebacks. Bot unchanged and not restarted; workspace fast-forwarded.
- Frontend `current`: `be2a40c7…` → `d225e33d…` (clean tagged clone, 2244
  tests and `tsc -b` passed). Entry `index-6U8qQMH3.js`; served `index.html`
  equals the release file; 6 affected assets match the manifest.
- Backup `.local/readonly-results-293-release-20261111T163949Z/dashboard.sqlite3`:
  integrity ok, equal to live; 162 participation records with 0 staff
  overrides. All 73 table counts identical before and after.
- Signed-in smoke by Shaka SKIPPED (no signed-in browser).
- Rollback: backend `release.conf` back to `backend/965c3f746b75793b37a1c7862de8a435e9e5fe76`
  then daemon-reload and restart `wu-cwl-demo-web`; frontend
  `switch-release.py be2a40c7ecdc128f7e4833b8f07c92ee50d1581c`. Never restore
  the database for a code rollback.

## Bonus and participation flow release — 2026-11-11 (backend and frontend)

- PR [#291](https://github.com/SirRuggie/WU_Python/pull/291) (prompt 228),
  merge commit `be2a40c7ecdc128f7e4833b8f07c92ee50d1581c`, local tag
  `bonus-flow-228-1`. Built and released by Shaka (Claude) on Ruggie's
  instruction in the thread "Audit bonus medals pages". Head `7241561`
  passed four independent reviews (last gap fixed and its mutation checked).
- Changes: bonus host check uses the season pool (fixes "Hosting clan is no
  longer an active Lazy clan in this season"); new read-only
  `GET /api/cwl/seasons/{id}/bonus-status`; any bonus in the previous 3 months
  blocks a Lazy bonus; shared step bar, outcome chips, clan cards, phone layout.
- Backend: `release.conf` WorkingDirectory `backend/14bcded8…` →
  `backend/be2a40c7…`; service restarted, PID 2779146 → 3031436, cwd verified.
  `/api/cwl/config` 200, anonymous `/api/cwl/seasons` and `bonus-status` 401,
  no tracebacks. Bot code unchanged and not restarted (the bot does not import
  the changed modules); workspace checkout fast-forwarded to `be2a40c7`.
- Frontend `current`: `c95dee7e…` → `be2a40c7…` through `stage-release.py`
  (clean tagged clone, `npm ci`, 2235 tests and `tsc -b` passed) and
  `switch-release.py`. Entry `index-BJNXaOik.js`; `index.html` SHA-256
  `b8c77c481b6c49fc38feb63dd004316eecbd3486be9246061d82a359520f5fd5` equals
  the served file; 9 affected assets match the manifest.
- SQLite online backup `.local/bonus-flow-228-release-20261111T150821Z/dashboard.sqlite3`:
  integrity ok, equal to live. Season 1 signups lazy 147, main 23. All 73
  table counts identical before and after.
- Bug evidence on the backup: season 1 has 8 Lazy hosting clans; the old rule
  accepted 6, the new rule accepts 8.
- Signed-in smoke by Shaka SKIPPED (built-in browser signed out; Chrome
  extension not connected).
- Rollback: backend `release.conf` back to `backend/14bcded82ca26147e146635acfe05d19a3017ab1`,
  `systemctl --user daemon-reload && systemctl --user restart wu-cwl-demo-web`;
  frontend `/home/ruggie/.local/share/wu-dashboard/switch-release.py c95dee7ec2b4da31d4931f7995960ce333d4c268`.
  No data migration; never restore the database for a code rollback.

## B-6 tab cleanup release — 2026-11-11 (frontend only)

- PR [#280](https://github.com/SirRuggie/WU_Python/pull/280), merge commit
  `3d04372aa4b9614489dfd0dcf1434c9c32d22033`, local tag `b6-tab-cleanup-1`.
  Shaka APPROVED head `5aa382a`. Released by Shaka (Claude).
- Frontend `current`: `38c68ae625d1de4292410e5b318cb87fbc9e1c0b` →
  `3d04372aa4b9614489dfd0dcf1434c9c32d22033` at 2026-11-11T01:59Z, through
  `stage-release.py` (clean tagged worktree, `npm ci`) and `switch-release.py`.
  The `web/cwl` diff from `38c68ae` contains only PR #280. Backend
  (`249a83e3`) and bot were not changed or restarted.
- Public entry `index-s3SoFMZS.js`, CSS `index-DXqKCkzK.css`; `index.html`
  SHA-256 `ad4cdf23c006814e36a3307f42e3e96e7f27332f05b3fcc242e723e214a6b1ce`.
  Index and 13 changed feature assets (ClanManagement, ModerationWorkspace,
  ServerManagement, RosterWorkspace, navList, FilterChips, TextCommands) match
  the manifest. `/api/cwl/config` 200, anonymous `/api/cwl/seasons` 401.
- SQLite online backup
  `.local/b6-tab-cleanup-release-280-20261111T015830Z/dashboard.sqlite3`:
  integrity ok, equal to live. Season 1: lazy 147 signups / 146 assigned /
  131 locks, main 23 / 23 / 23, publication version 6, roster revision 621.
  All 73 table counts identical before and after.
- Signed-in smoke by Shaka SKIPPED (built-in browser signed out; Chrome
  extension not connected). Signed-out home checked at 375 and 800 px. Ruggie
  checked Family clans, Moderation and an FWA tools setting signed in on his
  phone at 2026-11-11T02:10Z: "Looks good".
- Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 38c68ae625d1de4292410e5b318cb87fbc9e1c0b`.

## Moderation logging release — 2026-10-30

- PR #68 / `moderation-logs-1` at `c494022e924994435496c3e4f0722eb781460380` shipped bot → ready → backend → ready → frontend. Integrated 4,863 backend tests / 21 skipped / 162 subtests and 933 frontend tests passed; final tagged frontend tests/TypeScript/build passed, with only three documentation files changed from the integrated checked tree. Seventeen mocked release checks passed.
- Raw moderation settings stayed unchanged at revision 1 with read-only normalization: Join/Leave enabled at channel 1564485264364011580, Kick/Ban disabled with no channel, all forum tags null, exact before/after parity. Backups/counts, hashes and readiness are in [backend releases](dashboard-backend-releases.md#moderation-logs-1--october-30-2026).
- Claude's read-only smoke 98 passed; no production Send test or test Discord message. Three of eight avatar requests returned 503 with initials fallback; prompt 33 item 6 remains open. Mock transport evidence is not live Discord delivery proof.

## Back-to-top release — 2026-10-30 (historical)

- `back-to-top-1`, PR #65/tag `a8031084eed09ee89b8063828d4bc2c5d40cc628`, released frontend only. Claude's read-only 360px smoke 93 passed: hidden at the top, visible after three viewports down and 200px up, 139×44 target, tap returns to zero and focuses Build roster. Backend PID 2951316 and bot PID 2920748/invocations stayed unchanged.
- 924 frontend tests, TypeScript/build and isolated layout passed; review 91 confirmed three required and five extra mutations killed. Public entry/roster hashes, verified backup, protected digest and guarded rollback are in [frontend releases](dashboard-frontend-releases.md).
- Later from review 91: hide the button during the undo toast (about 12px overlap); confirm real-phone toolbar resize behavior that can require extra upward travel; add workspace-level bar-height and open-panel hide-gate tests. These remain open after the passing smoke.

## Trigger-delete and weight-range releases — 2026-10-30

- `trigger-delete-1`, PR #63/tag at `b517afd46ecfa9cc08488798eba53393ed5b649f`, released frontend/backend/bot. Plain and recipient trigger messages are deleted only after a successful reply when the new default-on option is enabled. Delete failures remain visible and later success clears the warning. Claude smoke 90 passed; Codex and Claude did not post a live trigger. Ruggie's own Discord test is separate.
- `weight-range-1`, PR #64/tag at `23235ccf2671dfe5675f0bc98d38ab11a011ab09`, released frontend/backend; bot stayed at b517afd, PID 2920748 with unchanged invocation. Inclusive range bounds, descending-weight Compare and capped quick picks passed Claude's read-only 360px smoke 92, including Jujupon 179k inside Lazy.128's 172–179 range.
- Tagged checks: trigger-delete 4,839 backend / 21 skipped / 133 subtests and 908 frontend; weight-range 4,844 backend / 21 skipped / 153 subtests and 914 frontend. TypeScript/build passed for both. Verified backups, public entry/feature hashes and protected-state comparisons are in [backend releases](dashboard-backend-releases.md#weight-range-1--october-30-2026).
- Tooling limits are recorded there: nested-asset staging fallback; trigger-delete first rolled back after a wrong journal window, then passed with InvocationID-scoped checks; weight-range's owning-bundle verifier corrected nonexistent standalone chunk assumptions. Preserve routing/storage drop-ins and all data during rollback.
- Later: prompt 31 fixes the pre-existing command pattern hyphen under browser `v` regex semantics. Prompt 32 cleanup retains the unreachable Max-50 branch, stale selection documentation and first-only shared-boundary note as review items. The zero-unlocked selection correction is carried by the separate accepted back-to-top change.

## Strike-tracking release — 2026-10-30 (historical)

- At that release, frontend/backend/bot were `strike-tracking-2`, `6a2f8d735d1ee6e5ea912be10d3bba75a143ce09`, PR #61. Claude read-only smoke PASSED; the official bot pass checked 25 clans, and Tracking showed 12 On track / 13 Behind, 0 private / 0 error. Public entry and feature hashes, backend readiness/cwd, protected data and durable backups passed. No historical gap backfill or live test messages. See `docs/strike-system.md` and `docs/dashboard-backend-releases.md` for policy, rollback and Later items.

## Weight totals release — 2026-10-29

- Previous frontend: `weight-totals-1`, `4f57d6e73941d3adc3b3223611927081bf794df9`, PR #59. Assign and Balance display known-weight totals instead of weight averages; `Avg TH` remains. Empty clans say `Total: no weights yet`. Fill spot / Signup Details no longer opens a second dirty dialog after roster Discard. The accepted branch passed 901 frontend tests, TypeScript/build and full isolated layout. Claude's read-only owner 360px smoke PASSED (handoff 65): Assign showed `Current total 2,652k` and the no-weights state; Balance showed totals without horizontal overflow or weight Avg labels. Only GETs appeared, with no console errors.
- Public `index-5dIAUgQj.js` SHA256 `b3f78cd7daba401cd67513e69fced2d6bf989e8a0b44b9e7f840d28a742d5c12` matched the release. Backend remained `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061, without restart. Config returned 200 and anonymous access 401. Protected signups/assigned/locks matched before and after: Main 22/18/18, Lazy 118/89/71. Backup `.local/weight-totals-1-backup-20261030T012727Z/dashboard.sqlite3`: 1,232,896 bytes, SHA256 `4a86e9aa42e477d87267e1bb9e77df8f6297bc3c6f02eac0ccb503f7a13bdeee`, integrity OK and all table counts matched. Evidence `/tmp/wu-weight-totals-release/`. Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 8c7b5a8c29c6dab65801879cf20226f94e7efc7c`.

## Roster hotfix release — 2026-10-29

- Previous frontend: `roster-hotfix-1`, `8c7b5a8c29c6dab65801879cf20226f94e7efc7c`, PR #57. Only hosting clans with assigned accounts count toward the missing-capacity warning, shown as one line. Unsaved roster navigation uses an in-app Discard / Keep editing dialog; in-flight saves show OK-only wait copy. Assign-mode pool filters still preserve selections without a discard prompt. Missing weights has one queue-level `Enter weights as: Loot | Full` control, default Loot, with unchanged save payloads and explicit Save.
- Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 30676446e559cab33d108aeb68711e74c8b98a33`. Backend remains `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no service or bot restart. Public `index-DKL_Envz.js` SHA256 `e077320fdc59a84311fba3c28069e3ea60f7b633fff9999063f8595164165b20` and release assets matched. Config returned 200 and anonymous access 401. Claude's read-only owner 360px smoke PASSED (handoff 62): one two-clan capacity line, one top weight-unit switch, and a dirty weight Discard opened Clan settings. Only GETs and Cloudflare's beacon appeared; no application writes or console errors.
- Backup `.local/roster-hotfix-1-backup-20261030T002634Z/dashboard.sqlite3`: 1,224,704 bytes, SHA256 `b116d76b7a4e0153c56020dce1eab445b1813348148d84faff5da9a42c2863ba`, integrity OK and all table counts matched. Protected signups/assigned/locks matched immediately before and after this release: Main 22/18/18, Lazy 118/89/71. Accepted branch: 899 frontend tests, TypeScript/build and isolated layout passed; the clean tagged release matched the accepted asset hash. Evidence `/tmp/wu-roster-hotfix-release/`. The duplicate `playerDirty` dialog for Fill spot / Signup Details was fixed in weight-totals-1.

## Roster readability release — 2026-10-29

- Previous frontend: `roster-readability-1`, `30676446e559cab33d108aeb68711e74c8b98a33`, PR #56. Desktop Accounts columns, shared MapPin location labels, slim publication status, separate amber signup changes and red shortage, edge fades, and no-weight total copy. Claude accepted the fixture review (handoff 55); 883 frontend tests, TypeScript/build, layout and four of five targeted mutations passed. Public `index-DWX3fCZu.js` SHA256 `48cf0177d49a4a1a25393fc1bb609ca65417b6a1a3d64123cf2dfdaea1704a18` matched the release.
- **Initial phone smoke FAILED** (handoff 56): 23 missing-capacity rows pushed the page down; a pre-existing native weight-draft confirmation silently trapped Android navigation; per-row Loot/Full toggles looked selected. The live release remained in place until roster-hotfix-1 addressed these issues. Readability's own backup `.local/roster-readability-1-backup-20261029T232554Z/dashboard.sqlite3` passed integrity/count checks; Main 22/18/18 and Lazy 118/92/74 matched across that deployment. Backend stayed at `f95830b`/PID 2249061 with no restart. Evidence `/tmp/wu-roster-readability-release/live-proof.json`. Do not describe this initial smoke as passed.

## Staff navigation release — 2026-10-29

- Previous frontend: `staff-nav-1`, `95808221f85200c3f51a9a036a6fbb266b2eda57`, PR #54. Flat staff groups, distinct icons and unchanged routes/permissions. Automatic current-group opening never persists; only explicit choices do. The tour temporarily shows only its target group.
- Frontend-only rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py ae511de81bde1a2220fa51f604125099a9caecee`. Backend remains `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no restart or bot change. Public `index-Dd77bclu.js`, SHA256 `a9745e061c0092a2b6baa8a85f74f297adc50305a80333e2d581290396d34a61`; index and 47 assets match the manifest, config 200, anonymous seasons 401, journal clean. Claude read-only owner smoke PASSED (handoff52): correct flat menu and saved preferences, no dialogs or errors.
- Backup `.local/staff-nav-1-backup-20261029T220729Z/dashboard.sqlite3`: 1,216,512 bytes, integrity OK and all 58 table counts matched. Protected records unchanged: Main signups/assigned/locks 22/18/18, Lazy 118/92/73. Clean tagged checkout: 865 tests, TypeScript/build passed. Full isolated layout passed at 360×800 and 1440×1000; five mutations caught. Evidence `/tmp/wu-staff-nav-release/`; no database restore for frontend rollback.
- Used the established recursive scratch staging helper for nested assets; installed helper and service config unchanged. Deferred moderation copy: `ModerationWorkspace.tsx` eyebrow “Server tools” belongs to the moderation batch.

## Owner prank speed release — 2026-10-29

- Previous frontend: `owner-prank-3`, `ae511de81bde1a2220fa51f604125099a9caecee`, PR #52. Cards advance immediately while confirmed progress writes serialize; all 13 private card images preload. An uncertain failure halts dependent writes without notification retries; cards remain viewable with an error, and reload resumes confirmed progress. Completion and replay remain server-confirmed.
- Frontend-only rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py b200c77d67f525a4a1afed515e2baed34dc31dd2`. Backend stays `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no restart or bot changes. Public `index-BBPDdxUl.js`, SHA256 `f9404755282073e043a96e9a533279589147bef9f3d202c28864111ad9fb7867`; index plus 47 assets match the manifest, config 200, anonymous seasons 401, clean journal. Claude infrastructure smoke PASSED (handoff 49), including anonymous prank state 404. Ruggie's replay experience check remains separate; no live DM delivery claim.
- Backup `.local/owner-prank-3-backup-20261029T212323Z/dashboard.sqlite3`: 1,216,512 bytes, SHA256 `9ac153db6f69019f75813df33988175bda8c73109a723ef4445325de99417d0c`, integrity OK, all 58 table counts matched. Protected signups/assigned/locks unchanged: Main 22/18/18, Lazy 118/92/73; publication/rule/weight/image records unchanged. Clean tagged checkout: 865 frontend tests, TypeScript/build passed. Accepted branch: full isolated layout passed. Evidence `/tmp/wu-owner-prank-3-release/`.
- Used the previously verified recursive scratch staging helper for nested assets; no installed helper or service configuration edits. No database restore for frontend rollback.

## Tour copy release — 2026-10-29

- Previous frontend: `tour-copy-1`, `b200c77d67f525a4a1afed515e2baed34dc31dd2`, PR #50. Tour card 5d now says “This button signs you up” and shows its practice guidance in two separate lines; review buttons visibly say “Change CWL” and “Change accounts”. Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 567cd2d37acdff6d27be62e42dfe8ceebb9df789`.
- Backend remains `owner-prank-1`, `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, PID 2249061; no restart. Bot unchanged. The public `index-DYh42jNc.js` and affected asset hashes matched the release. Config returned 200, anonymous access 401, and Claude's read-only smoke PASSED (handoff 47). This smoke did not test live owner DM delivery; Ruggie reported that the prank looks good but pauses between cards; entry 45 tracks the speed fix.
- Backup `.local/tour-copy-backup-20261029T205253Z/dashboard.sqlite3`: 1,216,512 bytes, SHA256 `b66137ba1c45ead853a3ec90c4aa8b4cff535fb54ef2c8d5607d5929aefd7df5`, integrity OK. All 58 table counts matched. Protected signups/assigned/locks stayed Main 22/18/18 and Lazy 118/92/73. The clean tagged checkout passed 850 frontend tests and TypeScript/build; the accepted frontend branch passed the full isolated layout suite. Evidence: `/tmp/wu-tour-copy-release/live-proof.json` and `backup-verification.json`.
- The installed `stage-release.py` first failed while handling the nested `assets/tour` directory. A corrected scratch copy staged the release; no production activation occurred before that correction. The original installed helper still needs its nested-assets handling fixed. Inode recovery removed only regenerable dependencies from inactive checkouts; evidence `/tmp/wu-tour-copy-release/inodes.json`.

## Owner prank release — 2026-10-29

- Previous frontend: `owner-prank-2`, `567cd2d37acdff6d27be62e42dfe8ceebb9df789`, at `/home/ruggie/.local/share/wu-dashboard/releases/567cd2d37acdff6d27be62e42dfe8ceebb9df789/`. It starts on the first dashboard page, including the PWA Tasks landing page, and defers while an editor is dirty or another dialog is open. Its frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py f95830b5b774ba34b29f4756a1cc9e3747148f1b`.
- Backend remains `owner-prank-1`, `f95830b5b774ba34b29f4756a1cc9e3747148f1b`, at `/home/ruggie/.local/share/wu-dashboard/backend/f95830b5b774ba34b29f4756a1cc9e3747148f1b/`; no restart for owner-prank-2. Bot unchanged. The earlier backend rollback is `8e0ee01337db50da8f2f289d257449c46440a440`; disable `PRANK_ENABLED` in the private environment file before a backend rollback. Retain the additive `owner_prank_state` table and all other database data.
- Owner-prank-2 backup `.local/owner-prank-2-backup-20261029T202118Z/dashboard.sqlite3`: 1,216,512 bytes, SHA256 `1bbadbf3926fa83be3b43db5103982dfcfea5b3e52f2ecc460e23b34bd0183ba`, integrity OK, all table counts matched. Protected signups/assigned/locks stayed Main 22/18/18 and Lazy 118/92/73. The owner-prank-1 migration backup is `.local/owner-prank-backup-20261029T194759Z/dashboard.sqlite3`.
- Public `index-BGemXK8m.js` SHA256 `615d4d3959b1c2edce25867a3e994bc6056d5c3345f1a146fc40204ec9a4e97d`; release entry `index.html` SHA256 `9af0db3958c2abfa75bc46f8a97b82975cb57abc4480b2dde95659d3ea70850e`. Claude read-only infrastructure smoke passed (handoff 44): public entry matched byte for byte, current symlink and backend cwd matched, anonymous prank state returned 404. Ruggie reported that the prank looks good but pauses between cards; entry 45 tracks the speed fix; no live DM delivery has been verified by Codex.
- Owner-prank-2: 850 frontend tests, TypeScript/build. Evidence `/tmp/wu-owner-prank-2-release/live-proof.json` and `backup-verification.json`. Owner-prank-1 backend: accepted 4,807 tests with 21 skipped; evidence `/tmp/wu-owner-prank-release/live-proof.json`.

```bash
# Frontend-only rollback from owner-prank-2 to owner-prank-1; backend stays unchanged.
/home/ruggie/.local/share/wu-dashboard/switch-release.py f95830b5b774ba34b29f4756a1cc9e3747148f1b
```

For an additional rollback of the original owner-prank backend, first set `PRANK_ENABLED=false` in the private `.local/cwl-web.env`, then use:

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py ef90834282142b1d924a9f24077d39f9b95105a4
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/8e0ee01337db50da8f2f289d257449c46440a440\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```

Verify readiness, runtime cwd and public hashes after rollback. Never restore a database to roll back code.

## Historical rollback targets (verified through 2026-10-29)

- **Previous frontend — Member signup polish (2026-10-29):** `ef90834282142b1d924a9f24077d39f9b95105a4`, tag `signup-polish-1`, PR #44. Prior release docs merged through PR #43.
  - Release `/home/ruggie/.local/share/wu-dashboard/releases/ef90834282142b1d924a9f24077d39f9b95105a4/`. Backend unchanged at `8e0ee01`, PID 1961058; no restarts.
  - Rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 539853ec37b62ad67a5157a8c10234688fc28af9`. Restore shared `assets/tour/SOURCES.md` from that release if rolling back provenance too. No database restore.
  - Verified backup `.local/signup-polish-backup-20261029T175358Z/dashboard.sqlite3`: 1,204,224 bytes, integrity OK, all 57 table counts matched. Main 21/18/18 and Lazy 114/92/73 unchanged (signups/assigned/locks), publications and protected records identical. Transient OAuth/session table activity is excluded only from activation equality, not backup verification.
  - Public `index-CcecPS0C.js`, SHA256 `d98a05b60ffca4c414f91fe7dac4c5de9de7527d1f574bdcda3289fc413d86ca`; index and 45 assets matched the manifest. Config 200, anonymous seasons 401, clean journal.
  - 804 frontend tests, TypeScript/build and full isolated layout passed. No backend source changes; prior backend suite 4,799 passed, 21 skipped. Claude smoke PASSED (handoff 30): 360px signup copy/art, icons, account menu, no overflow, GET only. Evidence `/tmp/wu-signup-polish-release/`.

- **Previous frontend — Signup card + tour refinements (2026-10-29):** `539853ec37b62ad67a5157a8c10234688fc28af9`, tag `signup-card-1`, PR #42.
  - Release `/home/ruggie/.local/share/wu-dashboard/releases/539853ec37b62ad67a5157a8c10234688fc28af9/`. Backend unchanged at `8e0ee01`, PID 1961058; no services restarted.
  - Frontend-only rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 8e0ee01337db50da8f2f289d257449c46440a440`. No backend restart or database restore.
  - Backup `.local/signup-card-backup-20261029T163441Z/dashboard.sqlite3`: 1,204,224 bytes, integrity OK, all 57 table counts matched. Main 21/18/18 and Lazy 114/92/73 unchanged (signups/assigned/locks), including publication and protected records.
  - Public `index--G6lVqgC.js`, SHA256 `52eff54228f85c7d0c0db4eac26c44ea550c6e2e3c37f2f13636226e7c3426e1`; public index and affected assets matched the manifest. Config 200, anonymous seasons 401, clean journal.
  - 788 frontend tests, TypeScript/build and isolated layout passed; 78 tour measurements, 24 cleanup scenarios and both required mutations passed. No backend source changed; prior 4,799 backend tests passed. Claude smoke PASSED (handoff 23): red card and dates at 360px, tour copy/replay, no overflow, GET only. Evidence `/tmp/wu-signup-card-release/`.

- **Previous frontend/backend — Tour/deadline hotfix (2026-10-29):** `8e0ee01337db50da8f2f289d257449c46440a440`, tag `tour-deadline-1`, PR #40.
  - Frontend/backend: `/home/ruggie/.local/share/wu-dashboard/{releases,backend}/8e0ee01337db50da8f2f289d257449c46440a440/`. Bot remains `16cc79e`; no bot restart.
  - Rollback frontend with `/home/ruggie/.local/share/wu-dashboard/switch-release.py 16cc79e7db39e3aaadf99c99117994b9103a47e8`; set only `release.conf` WorkingDirectory to `/home/ruggie/.local/share/wu-dashboard/backend/16cc79e7db39e3aaadf99c99117994b9103a47e8`, then `systemctl --user daemon-reload` and `systemctl --user restart wu-cwl-demo-web.service`. Restore shared `assets/tour/SOURCES.md` from that previous release if rolling back its provenance too. Never restore the DB for a code rollback.
  - Backup `.local/tour-deadline-backup-20261029T151849Z/dashboard.sqlite3`: 1,204,224 bytes, integrity OK, 57 table counts match. Main 21/18/18 and Lazy 114/92/73 unchanged (signups/assigned/locks), along with all protected records.
  - Public `index-DUNRfMkr.js`, SHA256 `25bdc11e4013c79ef2a70e10d15c6ecca02f27e823abd5e201fe05d68a2207c9`; 42 asset hashes verified. Two readiness 200s by 6.42s, isolated backend cwd verified, clean journal with `refreshed=1 failures=0`.
  - 782 frontend / 4,799 backend passed, 21 skipped; typecheck/build/layout and 24 cleanup cases passed. Claude smoke PASSED (handoff 17); Ruggie ran the real-page tour. November deadline correctly uses the stored October campaign: Oct 30 21:00Z; placements Oct 31 21:00Z. The initial Oct 29 expectation was corrected by Claude; the first attempt was safely rolled back before retry. Evidence `/tmp/wu-tour-deadline-retry/`.

- **Previous frontend/backend; current bot — Member tour + timing (2026-10-29):** `16cc79e7db39e3aaadf99c99117994b9103a47e8`, tag `member-tour-1`, timing PR #38 and tour PR #39.
  - Frontend/backend: `/home/ruggie/.local/share/wu-dashboard/{releases,backend}/16cc79e7db39e3aaadf99c99117994b9103a47e8/`; bot at the same SHA. Rollback all three to `5539cba3c800d91372fd5c6adc62564a758ddff4` using switch-release, release.conf + daemon-reload/dashboard restart, and bot reset/restart. Never restore the database for a code rollback.
  - Backup `.local/member-tour-backup-20261029T122118Z/dashboard.sqlite3`: 1,196,032 bytes, integrity OK, 57 table counts matched. Main 19/18/18 and Lazy 113/92/73 unchanged.
  - 774 frontend / 4,797 backend passed (21 skipped, 126 subtests); typecheck/build/layout including 78 tour measurements passed. Public `index-CKbJjEBO.js`, 28 asset hashes, backend cwd and bot startup verified. Timing refresh completes in 5.8s every five minutes.
  - Claude smoke **PASSED WITH DEFECTS — keep live**: 360px date line/invite/art, runtime/hashes, zero writes. Ruggie sees dates in Discord but the wrong campaign month. Original missing-date timeout fixed; wrong-month and real-page tour defects were fixed by tour-deadline-1; remaining spotlight sizing and copy refinements are queued under handoff prompt 11. Evidence `/tmp/wu-tour-release/live-proof.json`.

- **Previous frontend, backend and bot — Member signup (2026-10-29):** `5539cba3c800d91372fd5c6adc62564a758ddff4`, tag `member-signup-1`, PR #37; moderation preservation merged first through PR #36.
  - Frontend and backend under `/home/ruggie/.local/share/wu-dashboard/{releases,backend}/5539cba3c800d91372fd5c6adc62564a758ddff4/`; bot `/home/botrunner/wu-bot` at the same SHA.
  - Previous frontend/backend `2279c95c3bc62ac74447c4a66a0a924dde45bda4`; previous bot `2d7d2c92c246db886994dee8a3a515b6e0bf1076`.
  - Backup `.local/member-signup-backup-20261029T044244Z/dashboard.sqlite3`: 1,167,360 bytes, integrity OK, all 57 table counts matched; Main 19/18/18 and Lazy 95/92/73 signups/assigned/locks unchanged.
  - 761 frontend / 4,792 backend tests passed (21 skipped), typecheck/build/layout passed. Public `index-BosjyeFk.js` and 28 hashes verified; dashboard readiness and bot startup/gateway passed. Evidence `/tmp/wu-member-signup-release/retry-live-proof.json`.
  - Claude read-only web smoke passed; Ruggie confirmed private Discord My signups and accounts: "Yes that looks fine". Date-line defect: fix in progress (handoff prompt 01); the current 1.5-second Mongo budget is too short.
  - Rollback frontend with `switch-release.py 2279c95c3bc62ac74447c4a66a0a924dde45bda4`; set only `release.conf` WorkingDirectory to the matching backend directory, daemon-reload and restart dashboard. Bot rollback (only when approved): `sudo -n -u botrunner git -C /home/botrunner/wu-bot reset --hard 2d7d2c9`, then `sudo -n systemctl restart wu-bot.service`. Never restore the DB to roll back code.

- **Previous frontend + backend — Roster images:** `2279c95c3bc62ac74447c4a66a0a924dde45bda4`, tag `roster-images-1`, PR #35.
  - Release root `/home/ruggie/.local/share/wu-dashboard`: frontend `releases/2279c95c3bc62ac74447c4a66a0a924dde45bda4/`; backend `backend/2279c95c3bc62ac74447c4a66a0a924dde45bda4/`, PID 1639904 verified.
  - Previous frontend `190313b81f4c8373dc08f5a63fca966c6caffab2`; previous backend `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`.
  - Backup `/nvme0n1-disk/Projects/Bot - Warriors United/.local/roster-images-backup-20261029T030832Z/dashboard.sqlite3`: 1,142,784 bytes, integrity OK, all 54 existing table counts matched. Main 19/18/18 and Lazy 95/92/73 signups/assigned/locks unchanged.
  - The three additive image tables stay on rollback; never restore the DB to roll back code.
  - Public `index-DuQyJREr.js` and feature hashes matched. 753 frontend tests; 4,775 backend passed, 21 skipped; M16 killed. Claude read-only 360px smoke PASSED: Announcements loads, authenticated image reads 200, anonymous endpoints 401, no writes. November is hidden: channel pickers, statuses and Preview were not visible and were not checked live.
  - Evidence `/tmp/CWL-roster-images-release-2279c95.html` and `/tmp/wu-roster-images-release/live-proof.json`.

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 190313b81f4c8373dc08f5a63fca966c6caffab2
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```

- **Previous frontend — Declaration:** `190313b81f4c8373dc08f5a63fca966c6caffab2`, tag `declaration-1`, PR #34.
  - Release: `/home/ruggie/.local/share/wu-dashboard/releases/190313b81f4c8373dc08f5a63fca966c6caffab2/`.
  - Previous frontend / rollback: `c767b55c010dd0de82416301a2c60057775a3662`; command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py c767b55c010dd0de82416301a2c60057775a3662`.
  - Backend unchanged: `backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf`, PID 1366655, no restart.
  - Backup: `.local/declaration-backup-20261029T003303Z/dashboard.sqlite3`; 1,142,784 bytes, integrity OK, all 54 tables matched.
  - Public `index-B4f6VDw2.js` and 16 hashes verified; Main 19/18/18 and Lazy 93/92/73 signups/assigned/locks unchanged, all protected checksums identical.
  - 736 frontend tests, TypeScript/build and layout passed. Claude read-only 360px smoke PASSED: hidden version 1 message, no clan list, no errors. Clan sections verified on preview.
  - Evidence: `/tmp/wu-declaration-release/live-proof.json`.

- **Previous frontend — Details:** `c767b55c010dd0de82416301a2c60057775a3662`, tag `details-1`, PR #33.
  - Release: `/home/ruggie/.local/share/wu-dashboard/releases/c767b55c010dd0de82416301a2c60057775a3662/`.
  - Previous frontend / rollback: `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`; command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 73fe3fa92d8d0d89491be6e350c130b9d375aaaf`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`, PID 1366655; no restart.
  - Backup: `.local/details-backup-20261028T232301Z/dashboard.sqlite3`; 1,142,784 bytes, integrity OK, all 54 table counts matched.
  - Public `index-CsYgjk4R.js` and 15 asset hashes matched; Main 19/18/18 and Lazy 92/90/71 (signups/assigned/locks), publications, member season, signup activity and manual/saved weight checksums stayed identical.
  - 719 frontend tests, TypeScript/build and layout passed in the clean tagged checkout. Layout required `WU_TEST_PYTHON` to point to the existing interpreter.
  - Claude read-only 360px smoke PASSED, relayed by Ruggie: open/Next/focus/Back retain account URLs, direct link opens Ace, clean Save disabled; no errors or writes.
  - Evidence: `/tmp/wu-details-release/live-proof.json`.


- **Previous frontend/backend — Announcements:** `73fe3fa92d8d0d89491be6e350c130b9d375aaaf`, tag `announcements-1`, PR #32.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/73fe3fa92d8d0d89491be6e350c130b9d375aaaf/`; approved isolated restart, PID 1366655 at verification.
  - Previous frontend / rollback: `4404c3672872ebff706519402efa4ee9940d3a60`; previous backend / rollback: `61290a4ce2b87611119483d6376b879a675aeb81`.
  - Backup: `.local/announcements-backup-20261028T205112Z/dashboard.sqlite3`; 1,138,688 bytes, integrity OK, all 54 table counts matched.
  - Deployment signups/assigned/locks unchanged: Main 19/18/18; Lazy 91/90/71. Publication v1 remains withdrawn, member season 1/revision 0, unreviewed signup activity 1 and November 2026 Manage binding unchanged.
  - Public `index-Dn86Au-2.js` and feature hashes match the manifest; config readiness passed twice consecutively; unauthenticated Manage read returns 401; clean restart journal. 681 frontend tests, 4,702 backend tests (21 skipped), TypeScript/build, layout and all four send-guard mutations passed.
  - Claude read-only 360px smoke PASSED, relayed by Ruggie: entry/backend, hidden status line, real channels/roles, Preview, Edit opened/closed with no unsaved change; zero write requests, no errors, clean journal.
  - Evidence: `/tmp/CWL-announcements-release-73fe3fa.html`, `/tmp/wu-announcements-release/live-proof.json`.

Rollback both code layers (never restore the DB to roll back code):

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 4404c3672872ebff706519402efa4ee9940d3a60
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
readlink /proc/$(systemctl --user show -p MainPID --value wu-cwl-demo-web.service)/cwd
```

- **Previous frontend — Signup changes:** `4404c3672872ebff706519402efa4ee9940d3a60`, tag `signup-changes-1`, PR #31.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/4404c3672872ebff706519402efa4ee9940d3a60/`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`; PID 1053095, no restart.
  - Previous frontend / rollback: `00170063e15b7df43bd769f2c97b0a69bd0ebdf5`.
  - Rollback command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 00170063e15b7df43bd769f2c97b0a69bd0ebdf5` (frontend only).
  - Backup: `.local/signup-changes-backup-20261028T191131Z/dashboard.sqlite3`; 1,138,688 bytes, integrity OK, all 54 table counts matched.
  - Deployment signups/assigned/locks unchanged: Main 19/18/18; Lazy 91/90/71. Publication version 1 remains withdrawn; member season 1/revision 0 unchanged. Unreviewed signup changes 1 → 1; reviewed rows 41 → 41.
  - Public entry `index-DptKfiRQ.js` and roster hashes matched the manifest; 657 frontend tests, TypeScript/build and layout 10/10 passed. Evidence: `/tmp/wu-signup-release/live-proof.json`.
  - Claude read-only smoke PASSED, relayed by Ruggie: at 360px the shortage-first alert fits, panel opens/closes without review (1 still unreviewed), summary shows “+21 clans with no players”, inline emoji is 22px, cards are 74px, and no errors occurred.

- **Previous frontend — Player card 3:** `00170063e15b7df43bd769f2c97b0a69bd0ebdf5`, tag `player-card-3`, PR #30.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/00170063e15b7df43bd769f2c97b0a69bd0ebdf5/`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`; PID 1053095, no restart.
  - Previous frontend / rollback: `374e0995280dad7d13483a2fa655975d0af72280`.
  - Rollback command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 374e0995280dad7d13483a2fa655975d0af72280` (frontend only).
  - Backup: `.local/player-card-3-backup-20261028T173130Z/dashboard.sqlite3`; integrity OK, 54 table counts matched. Signups/assigned/locks unchanged: Main 19/18/18; Lazy 90/83/64. Publication and member-season unchanged.
  - Public entry `index-CScTR1be.js` and feature hashes matched; 634 frontend tests and clean tagged TypeScript/build passed. Evidence: `/tmp/wu-player-card-3-release/live-proof.json`.
  - Claude read-only smoke PASSED, relayed by Ruggie: release/build, backend unchanged, line 2 one line on all 19 Main cards, no errors.


- **Previous frontend — Player card v2:** `374e0995280dad7d13483a2fa655975d0af72280`, tag `player-card-2`, PR #29.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/374e0995280dad7d13483a2fa655975d0af72280/`.
  - Backend unchanged: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`; PID 1053095, no restart.
  - Previous frontend / rollback: `61290a4ce2b87611119483d6376b879a675aeb81`.
  - Rollback command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py 61290a4ce2b87611119483d6376b879a675aeb81` (frontend only; no backend restart).
  - Scripted public index/feature hashes, counts, publication and member-season checks passed. Main 19/18/18 and Lazy 89/83/64 unchanged during deployment. No backup required by the approved frontend-only release prompt.
  - Claude read-only smoke PASSED, relayed by Ruggie: build, strip dot, hidden banner, 109 cards, line 3 all correct. Real long-tag line-2 polish is a separate preview batch.
  - Evidence: `/tmp/wu-player-card-2-release/live-proof.json`; 631 frontend tests and clean tagged TypeScript/build passed.


- **Previous CWL flow frontend/backend:** `61290a4ce2b87611119483d6376b879a675aeb81`, tag `cwl-flow-1`, PRs #27 (`3631408`) and #28 (`61290a4`).
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/61290a4ce2b87611119483d6376b879a675aeb81/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/61290a4ce2b87611119483d6376b879a675aeb81/`.
  - Previous frontend + backend: `1a8b035461ec46fba60f6ed4808111d3c67d87cf` (`finalize-1`).
  - Backup: `.local/cwl-flow-backup-20261028T145938Z/dashboard.sqlite3`; integrity OK, all 54 table counts matched, 1,134,592 bytes. The activation recheck found no changes, so this remained the baseline.
  - Readiness: public config returned 200 twice at 5.15/6.21 seconds; service/cwd, public entry and roster/publication/seasons hashes passed; lookup/publication unauthenticated reads returned 401. Main 19/18/18 and Lazy 87/83/64 (signups/assigned/locks), publications, weights, lineup/rules, season state and member-season remained identical.
  - Claude's read-only production smoke passed (relayed by Ruggie): sidebar, Build/strip/cards, Clan settings Add panel (Close only), Seasons and Finalize; no errors. No production writes during smoke.
  - Validation: 607 frontend tests, typecheck/build; 4,701 backend passed, 21 skipped.

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py 1a8b035461ec46fba60f6ed4808111d3c67d87cf
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/1a8b035461ec46fba60f6ed4808111d3c67d87cf\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```


- **Previous Finalize frontend + backend:** `1a8b035461ec46fba60f6ed4808111d3c67d87cf`, tag `finalize-1`, PR #26.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/1a8b035461ec46fba60f6ed4808111d3c67d87cf/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/1a8b035461ec46fba60f6ed4808111d3c67d87cf/`.
  - Backup: `.local/finalize-backup-20261028T040608Z/dashboard.sqlite3`; integrity OK, all 54 table counts matched, 1,122,304 bytes.
  - Scripted checks passed: active service/cwd, public entry and roster/publication hashes match manifest, unauthenticated publication GET returns 401. Protected data unchanged: Main 18/18/18; Lazy 84/84/65 (signups/assigned/locks), plus publications/instructions, weights and rules.
  - Authenticated metadata read and click smoke are delegated to Claude; Ruggie approved leaving the release live after scripted checks. No Publish or Hide submitted.
  - Previous frontend: `e6353fb9ef77244a6b366550f030d7fd8e75daf7`; previous backend: `c19db57523928f6fee9d6bc93d95d83fa5814bb0`.

```bash
/home/ruggie/.local/share/wu-dashboard/switch-release.py e6353fb9ef77244a6b366550f030d7fd8e75daf7
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user restart wu-cwl-demo-web.service
```

- **Previous Weights frontend:** `e6353fb9ef77244a6b366550f030d7fd8e75daf7`, tag `weights-1`, merged via PR #25.
  - Release: `/home/ruggie/.local/share/wu-dashboard/releases/e6353fb9ef77244a6b366550f030d7fd8e75daf7/`.
  - Frontend rollback: `/home/ruggie/.local/share/wu-dashboard/switch-release.py c19db57523928f6fee9d6bc93d95d83fa5814bb0`.
  - Reactivate Weights: `/home/ruggie/.local/share/wu-dashboard/switch-release.py e6353fb9ef77244a6b366550f030d7fd8e75daf7`.
  - Backend unchanged, **no restart**: `/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`; PID and cwd verified before/after.
  - Backup and retained frontend snapshot: `.local/weights-backup-20261028T022902Z/`. SQLite integrity ok, 54 table counts matched, 1,122,304 bytes.
  - Season 1 protected counts unchanged: Lazy 84 signups / 84 assigned / 65 locks; Main 18 / 18 / 18; publication version 1. All 102 manual-weight rows (26 non-null), 27 saved weights and lineup rules identical.
  - Public entry and roster JS/CSS hashes match the manifest. Authenticated smoke: type/clear only, Details open/close, no Save or Publish, no console errors.
  - Clean tagged checkout with `npm ci`: 542 frontend tests, TypeScript and build passed. Three missing-guard mutations caught.
  - Rollback on count mismatch, load errors or staff-reported write issues. Never restore the database just to roll back the frontend.

- **Previous Clan settings frontend / previous backend:** `c19db57523928f6fee9d6bc93d95d83fa5814bb0`, tag `clan-settings-1`, merged via PR #24.
  - Frontend: `/home/ruggie/.local/share/wu-dashboard/releases/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`.
  - Backend: `/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`, clean tag archive.
  - Frontend rollback: `a65b98ecc5c8d58601ec69d3efd184419b649e73`; backend rollback: `2f7ae7a53cedd70d9485dfd75151533194c69e01` (clean pre-merge archive).
  - Backup: `.local/clan-settings-backup-20261028T011847Z/`; integrity ok, all 54 table counts matched.
  - Post-deploy signups/assignments/locks/publication and lineup rules unchanged; public asset hashes and authenticated read-only smoke passed.
  - Backend must never run from the workspace. See [isolated backend procedure](dashboard-backend-releases.md).

```bash
# Frontend rollback:
/home/ruggie/.local/share/wu-dashboard/switch-release.py a65b98ecc5c8d58601ec69d3efd184419b649e73
# Backend rollback (preserves frontend-routing.conf and storage-guard.conf):
printf '[Service]\nWorkingDirectory=/home/ruggie/.local/share/wu-dashboard/backend/2f7ae7a53cedd70d9485dfd75151533194c69e01\n' > /home/ruggie/.config/systemd/user/wu-cwl-demo-web.service.d/release.conf
systemctl --user daemon-reload
systemctl --user show -p WorkingDirectory,DropInPaths wu-cwl-demo-web.service
systemctl --user restart wu-cwl-demo-web.service
readlink /proc/$(systemctl --user show -p MainPID --value wu-cwl-demo-web.service)/cwd
```

To reactivate this release, use `switch-release.py c19db57523928f6fee9d6bc93d95d83fa5814bb0` and set the same drop-in's `WorkingDirectory` to `/home/ruggie/.local/share/wu-dashboard/backend/c19db57523928f6fee9d6bc93d95d83fa5814bb0/`, then daemon-reload and restart as above. Never remove the drop-in to roll back: that would restore the unsafe workspace directory.


- **Previous Compare clans release:** `a65b98ecc5c8d58601ec69d3efd184419b649e73`, tag `compare-clans-1`, merged via PR #23.
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/a65b98ecc5c8d58601ec69d3efd184419b649e73/`
  - Public entry and roster/publication feature hashes verified; authenticated read-only smoke passed; protected counts unchanged.
- **Older Release 1 rollback:** `fea7e668b21823d9e31943867e25654ce0d60bf8`.
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/fea7e668b21823d9e31943867e25654ce0d60bf8/`
  - Command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8`
  - Verified DB backup and frontend snapshot: `.local/compare-clans-backup-20261027T230301Z/`. UI rollback must never restore this database over later edits.


- **Original roster UI, before Release 1:** `bad19e1bf3b71cddcb87e26f9f926c676e87a31b` (parent of the first Release 1 commit, `ee1023e`).
  - Path: `/home/ruggie/.local/share/wu-dashboard/releases/bad19e1bf3b71cddcb87e26f9f926c676e87a31b/`
  - Clean detached checkout build; locked dependencies; 396 frontend tests passed; TypeScript and Vite build passed. Artifact hashes are recorded in `/home/ruggie/.local/share/wu-dashboard/manifests/bad19e1bf3b71cddcb87e26f9f926c676e87a31b.json`.
  - Standby only: built and staged, **not activated**. Production now runs the CWL flow frontend and backend listed above.
  - This restores the entire older frontend, including older moderation screens. It does not revert backend code or data. Live compatibility has not been smoke-tested; use the preserved live snapshot when that is the appropriate rollback.
  - Activation, only when explicitly authorized: `/home/ruggie/.local/share/wu-dashboard/switch-release.py bad19e1bf3b71cddcb87e26f9f926c676e87a31b`
- **Pre-deploy snapshot (already includes early Release 1 UI):** `/home/ruggie/.local/share/wu-dashboard/releases/snapshot-20261027T171555Z/`. This is not the original roster UI.
  - Command: `/home/ruggie/.local/share/wu-dashboard/switch-release.py snapshot-20261027T171555Z`
- **Return to deployed Release 1:** `/home/ruggie/.local/share/wu-dashboard/switch-release.py fea7e668b21823d9e31943867e25654ce0d60bf8`

Switching the frontend never rolls back signups, assignments, locks or publications. Never restore a database merely to roll back UI assets.
