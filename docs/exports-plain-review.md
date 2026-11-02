# Exports: names and preview behaviour

Prompt 130 changes the frontend presentation only. Page title, navigation and the
Results/Bonus tab say **Exports**. The Data selector keeps its existing API values:

| UI option | Existing kind | Roster basis sent |
|---|---|---|
| Roster | `accounts` | `current` or `published` |
| Signups | `participation` | `current` |
| Results history | `participation-history` | `current` |
| Bonus medals history | `bonus-history` | `current` |

Roster version labels are Working roster and Published roster (v6). A disabled
published option explains that no roster is published, or that its status is
still being checked/unavailable. A known version remains visible while its
preview loads. No backend route, schema, authorization, CSV column or value
changes. The two App changes are Exports label literals only; routing is untouched.

## Current season and downloads

The shared App season loader already selects an available season for a fresh
`/cwl/exports` link, like Results and Bonus. This batch verifies that behaviour
rather than adding a competing default. Both a fresh link and an explicit
available `?season=` choice are tested. Changing season and browser Back keep the
chosen season. The existing shared loader's broader selection policy is unchanged.

Preview-only helpers reuse the existing compact roster weight and month label
helpers: 179000 displays as 179k and 2026-11 as November 2026. CSV downloads still
receive the original Blob without rewriting it. Blank mismatched results have
one short explanation pointing to Results history. The removed frozen/current
basis paragraphs are not replaced with new promises about data immutability;
the existing CSV disclosure still states that the file reflects saved data at
download time.

Download is disabled when the saved row count is 0, with a matching handler guard.
A search with 0 matches does not disable a file containing saved rows: the UI
explicitly says the CSV includes all saved rows regardless of search.

A recoverable download failure says Download failed and offers Retry. Retry is
the same safe GET, never a notification or mutation. 401/403 removes protected
preview data and offers no Retry, for both preview and download failures. The
existing authorization-change event remains intact. Aborts, stale response
checks and the pending-download ref prevent old contexts or duplicate clicks
from starting an extra file.

## Evidence and limits

The isolated fixture uses actual application export handlers, local SQLite and
fictional providers. Backend network guards reject external/default/production
services. Its exported_at_utc is fixed only in the fixture so time does not
invalidate byte comparisons; publication/results/bonus values remain normal
saved fixture data. 26 accounts include an escaped name, a spreadsheet-formula
name, different working/published weights, a mismatched result, saved results
and bonus selection history. The latest publication is fixture version 6.

- Full frontend suite: 1498 tests across 263 files. TypeScript/build passed.
- 25 focused component/helper/navigation cases cover dataset labels, preview-only
  formatting, stable publication labels, zero rows, exact CSV Blob passing,
  five existing UI request variants, duplicate pending clicks, denied access,
  stale previews and direct/explicit season links.
- Three genuine mutants are killed: zero-row download enabled, denied Retry
  shown, and a stale preview replacing a newer season's data.
- Eight raw CSV variants (four existing kinds × two bases) match byte-for-byte
  before/after. All five UI-accessible variants also match across the old and
  new frontend downloads. Retry produces the same CSV bytes. Full weights,
  month strings, columns, BOM and formula escaping are unchanged.
- Browser checks cover the direct route, season change and Back, 0-row disable,
  real fixture 500 retry and 403 denial, keyboard disclosure and Retry, and
  settled 360/1440 layouts for roster, empty, retry and denied states. No overflow;
  visible controls meet 44px targets. The narrow roster/retry and wide denied/empty
  screenshots were visually reviewed. Existing native form controls and focus
  styles are retained; no modal, sticky bar or new animation is introduced.

Evidence lives under the review worktree's `.local/p130-*`: focused/full frontend
and build logs; `p130-mutants/results.json`; fixture baseline CSVs and
`csv-byte-equivalence.json`; browser proofs, downloads and before/after
screenshots. Browser traffic outside the fixture is blocked; external image
requests use local placeholders. There were no production API calls, writes,
sends, or live delivery tests. No backend full-suite claim is made for this
frontend-only batch.

Initial harness failures are retained: sandboxed npm install could not execute
esbuild validation; the permitted offline isolated install succeeded. The
fixture's first bonus settings omitted a hosting clan and correctly returned 409;
the fixture was corrected. Chrome initially hit a long Unix-socket path, fixed
with a short symlink to on-disk workspace temp storage. A same-value synthetic
select event and an alert locator were corrected in the browser harness. Final
screenshots wait for responsive transitions; earlier transitional images are
retained but are not the visual sign-off evidence.

The persistent review URL uses `/cwl/exports` with Open local test session.
The fixture remains alive for review. Release is a separate root-owned action
after Claude's ACCEPT under approval 395, with the usual fresh release gates.

## Reproduce the isolated browser check

From the review worktree, after building the frontend to a private output path:

```bash
mkdir -p .local/p130-tmp
TMPDIR="$PWD/.local/p130-tmp" "$WU_TEST_PYTHON" web/cwl/tests/fixtures/exports_dashboard.py .local/preview-dist 0 .local/fixture-evidence
```

The fixture prints its owned port and writes ready.json and eight baseline CSVs.
In a second terminal, from the same worktree:

```bash
TMPDIR="$PWD/.local/p130-tmp" node web/cwl/tests/exports-plain.browser.cjs .local/fixture-evidence after .local/browser-evidence
```

Chrome may need a short symlink to that on-disk temp directory for its Unix
socket path; the actual temporary files must remain on disk under `.local`.
Use a fresh output directory to retain earlier evidence. The runner refuses
production/default fixture ports, blocks external traffic and performs only
fixture login, safe reads/downloads and local failure controls.
