# Participation waiting wording

Prompt 104 distinguishes a normal wait for a current/next CWL month from a real
source problem. It does not fabricate participation, start capture, fetch old
wars, change manual results, or alter authorization and refresh intervals.

## Rule

A normal wait requires all of the following:

- The selected cycle is the current or next month in UTC, including year rollover.
- A structurally valid league group belongs to the requested clan, but its reported
  month is older than the selection and no older than the previous calendar month.
  Thus current-month data can be normal while next month is selected. An ancient
  last-participation group remains a mismatch warning.
- Every failed group is that recent older-month case. An outage, malformed response,
  later reported month, or mismatched war response cannot be hidden by another clan
  that is merely waiting.
- No matching-month participation war response has already been observed anywhere
  in this dashboard. Preparation responses count conservatively as evidence the
  month exists in Clash. A current war in one clan keeps a real warning for another
  mismatched clan; current results are still retained.

The backend records the derived status `waiting`, with the selected month's name:
`November CWL hasn't started in Clash yet`. The UI renders that phrase once in the
capture status and suppresses the aggregate incomplete/stale/unavailable count
only for that explicit status. It does not infer waiting from the calendar alone.
Account values remain unknown rather than zero, and per-account source detail is
retained. Other status warnings and incomplete counts remain discoverable.

A cached wait becomes a real mismatch if the selected month is no longer current/
next or a matching-month war is subsequently observed. It becomes stale if its
last check is invalid or over 30 minutes old. These are read-time projections;
they do not mutate saved results on GET or add a scheduler or request loop.

## What the provider code proves

`LiveProviders.league_group` requests the official current-group route
`/clans/{tag}/currentwar/leaguegroup`; there is no selected-month parameter. It
returns the API's `body.season` unchanged. Participation previously compared that
reported month with the configured cycle and produced a mismatch for any
inequality. This explains why selecting a month ahead of the returned group can
produce the old warning. It does **not** prove Clash always returns last month's
group before an event. This change requires an actually observed, validated recent
older group; it never assumes that behavior on an unavailable or malformed read.
No live Clash call or production Check Clash action was used to prove this rule.

## Validation

- 45 focused backend tests cover current and next month, year rollover, past/later/
  ancient months, previously observed wars, stale cached waits, malformed/outage
  data, mixed-clan failures, partial current wars, complete results, and existing
  manual override/publication/freshness boundaries.
- Full frontend: 1,427 tests in 252 files, TypeScript and production build passed.
  Six new UI/helper cases keep waiting, later mismatch, partial, unavailable and
  complete distinct, verify one selected-month phrase, preserve real warning
  counts and make only read requests.
- Three genuine behavioral mutants were killed: a later month classified as an
  older wait, real-warning incomplete counts hidden, and duplicate waiting text.
  Disposable mutation exports were removed after preserving assertion logs.
- Actual App layouts with 170 synthetic accounts covered waiting/later/partial/
  unavailable/complete at 320, 360, 390 and 1440 pixels. All 20 states used GET-only
  detached API data, had no horizontal overflow or page errors, and fetched no
  closed history. Narrow/wide waiting and real-warning screenshots were visually
  reviewed. Existing controls and focus behavior are unchanged; controls retain
  the dashboard's target sizing. No save, notification, role or nickname action
  was performed.

Evidence is in `.local/p104-*`. The isolated preview is read-only and labels its
synthetic state controls. This is not deployment evidence or live delivery proof.

## Release

Ruggie authorized release after review in Claude entry 337, replacing the earlier
hold. Require Claude ACCEPT and normal fresh backup/test restore, protected counts,
no queued work, readiness, rollback, public hashes and read-only smoke. Backend and
frontend need updating; the bot does not need a restart for these files. Preserve
any newer deployed features and do not overlap the prompt 97 activation.
