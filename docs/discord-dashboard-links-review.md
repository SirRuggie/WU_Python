# Discord dashboard links and default copy (127 / 412)

Source only; release held for owner preview. No production campaign, message or database write occurred. Frontend/tour source is untouched.

## Message inventory

| Message | Dashboard equivalent / change |
| --- | --- |
| New Main roster default | Exact approved body; My clan assignments, My tasks, Wars |
| New Lazy roster default | Exact approved body; same three links plus unchanged LazyCWL Guide |
| Signup/reminder defaults | Existing signup/check controls; FWA rule above ordered steps, one shorter prefix |
| Existing saved/legacy/custom campaign | Exact previous normalization; no adoption of new defaults |
| `/cwl` member panel | Native controls retained; assignments/tasks/wars links |
| Declaration missing-player ping | Assignments on every chunk; same recipients/clan join links |
| Return/closing messages | Assignments/tasks/wars, approved status label |
| Regular war reminders | My tasks/Wars; same mention scope, timing and receipts |
| FWA war plans | My tasks/Wars; substantive instructions retained |
| Task panel/retired status | My tasks/Wars; component headroom recalculated |
| Read-only clan directory | Existing `/clans` destination centralized |
| Raids/games/gauntlet/BAND/unrelated staff tools | No matching member page; no misleading link added |

URLs live in `utils/dashboard_urls.py`. Main/Lazy roster buttons are 3/4; no row exceeds five. Declaration batching reserves one assignment button and counts nested/text budgets; 65-clan fixtures preserve recipients. Task pagination reserves two extra component units.

## Provenance and saved-copy preservation

Approval412 permits strict integer `default_copy_version: 127` only for genuinely new defaults. It survives a new local draft/Save/reload and keeps short reminder help once. No marker is backfilled. Old/unmarked/unknown-version, partial/missing-field, legacy, current/prior/future and custom records retain previous fallback/normalization. An unmarked custom body containing the new short line still receives the original legacy help normalization exactly. Unmarked cycles cannot inherit a marker from monthly defaults. Reads do not rewrite records.

The public campaign-domain defaults baseline is reused by the native editor without importing cycle custom copy or dashboard modules. The `Lazy Way or No Way` constant, roles, destinations, schedules, occurrence identities, sent guards and retry policy remain unchanged.

The existing Discord `/manage` editor supports Edit text and Edit buttons (label/URL/emoji, five-button limit). The web signup editor intentionally locks buttons; no new editor was invented. Update post is a separate authorized feature; this change never edits an existing message.

## Evidence

- Earlier218 targeted message/campaign checks passed. Marker/draft/OAuth group58, broader message/campaign group183 and marker/task/read-budget group94 passed (overlap is not a unique total).
- Checked-in prechange normalized fixture and public-load snapshots preserve old missing/empty/partial/full/current/prior/future/legacy cases. Read-only loads do not write markers.
- Authorized LOCAL backup comparison is **2026-11-02 16:14:49 UTC, NOT fresh/current**: three selected campaign records, normalized results deeply equal before/after. Both roster body/button sets match old defaults and differ from new defaults; hashes/match summaries only, no unrelated config copied/printed.
- Fully mocked OAuth roundtrip validates signup/assignments/tasks/wars return routes without linked accounts. Signed-in unlinked members keep existing linking/empty guidance, not invented forced login.
- Five genuine mutants killed: wrong task route, missing declaration link, overwritten legacy copy, unmarked custom short-help mistaken for new copy, and omitted new-default marker. Originals restored.
- Hostname grep finds only central URL constants and the existing canonical-host error instruction in bot/HTTP Python source. Legacy host compatibility is centralized.
- Required war-reminder gate passed: 213 backend / 1 skipped, 35 frontend, TypeScript and isolated build. Final marker/copy freeze: 24 focused passed. Final guarded full backend passed: 6343 tests / 99 skipped / 267 subtests in 581.75 seconds; external/default service ports were blocked. No frontend source changed, so no full frontend/browser rendering claim is made.

## Adversarial review / limits

Fixed public destinations and existing OAuth return sanitization reject foreign-origin return links. Mention recipients/flags, event timing and uncertain-delivery behavior are unchanged. Button/text/nested limits and native transport forwarding are tested. Existing owner/draft/editor validation remains authoritative. Fake OAuth/transport/component tests are not live Discord rendering or delivery proof. A future approved release needs a bot restart but sends/edits nothing on activation.

The required shared roster-redesign paragraph is included in this branch after its frozen owner explicitly released append ownership; no concurrent shared-document edit was made.

The first full backend run completed with 6340 passes and two obsolete copy expectations: the closing link still expected “My assignments”, and the help-footer test required the old long line in new marked reminders. The corrected footer regression now checks both old/unmarked and new marked defaults, preserving exact footer/button structure and one intended body check line. Runtime source was unchanged by these test corrections; the final full rerun passed as recorded above.

## Local owner preview

`http://127.0.0.1:34217/` (static PID2566239) is a disconnected read-only catalog generated from all 14 actual native payloads (seven message types × Main/Lazy). It displays exact text and button destinations; Markdown is verbatim and artwork is not fetched. It does not send/edit Discord messages, change saved campaigns or claim live Discord rendering. Local payload evidence is retained under `.local/p127-preview`; production frontend source remains untouched.
