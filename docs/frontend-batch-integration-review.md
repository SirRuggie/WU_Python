# Frontend batch integration review

This local integration follows Shaka 513 on main
`a9b12fbbb5def06a0d7c32be11e118bd4119884b`. It includes only `web/cwl`
and the corresponding frontend review documents. It does not include backend,
bot, tools, deployment configuration, or unrelated stacked-branch documentation.
No production operations or remote branch publication formed part of this review.

## Provenance

Each row applies the accepted revision's scoped full-index patch relative to the
listed predecessor, rather than checking out its stacked tree wholesale.

| PR | Accepted revision | Patch predecessor | Local commit |
| --- | --- | --- | --- |
| 184 | `93a5b1791662594e185065767e52ccd2397ca627` | `fe67907beb09c5638e4a0b873be0b60f2bdfffc5` | `5c55921b` |
| 188 | `177e2f3342706cdac0cdbe22627e914ff929bd41` | accepted 184 | `99f31a02` |
| 185 | `487d536c01c79848f416677d8bf78692cb57d13b` | `fe67907beb09c5638e4a0b873be0b60f2bdfffc5` | `f52902a1` |
| 191 | `20b9e580b2c8f5dd0a4b935e11ee22a1a2baa45d` | accepted 188 | `36bba0ac` |
| 192 | `ae89a10449fc880885c0b446019a97247f232ea2` | accepted 191 | `c5853cc7` |
| 193 | `568e40e6f50fbfe59dbcec6d3f74004a57919b43` | accepted 192 | `901febc2` |

The base frontend is byte-equal to the common predecessor. PR191's stacked range
also contains 26 backend/bot paths and two unrelated release documents; these were
excluded explicitly. Exact path lists, patch hashes, proposals, source audit and
logs are retained in `.local/integration/provenance.json` and adjacent files in
the isolated integration checkout.

## Reviewed conflicts

The 184 documentation append preserves the entire main document followed by the
exact accepted suffix. The 185 import/test/document append preserves both imports,
every test group and both document sections; the parent reviewed these proposals.

Integration stopped at the 191 ArrivalCheck behavior conflict. Shaka 514 approved
the exact proposal: use 191's layout, retain 185's lifecycle and shared filler
queue, and preserve these bindings:

- Pool discard clears only the ping draft; pending filler work remains dirty.
- Ping working and dirty callbacks include the filler queue's working state.
- The relocated Details request receives the shared queue and explicit refresh.
- Compact Refresh remains disabled during explicit refresh or filler work and
  completes only after the matching reads.

The 192 conflict was additive: render its native confirmation dialog and the full
185 not-saved alert. The parent reviewed the exact proposal. Both accepted test
groups remain; the combined held-queue test uses native Cancel/Discard. PR193
applied cleanly. No other runtime conflict was resolved implicitly.

## Validation

The integrated frontend passed 1,741 tests in 292 files, followed by TypeScript and
the production build. Focused intermediate runs passed 68 tests after 185, 74 after
191 and 76 after 192. Combined regressions exercise a held filler save, ping false
callbacks, pool discard cancellation/confirmation, and actual App parent Next
blocking. Three private mutations removing the working OR, dirty OR or pool dirty
retention each fail the combined regression.

The checked-in same-look suite passed 30 narrow/wide cases, including dialog and
reduced-motion checks, with no recorded writes or page errors.

The checked-in density suite passed 52 cases across 320, 360, 390 and 1440 pixels,
with 26, 65 and 125 accounts: no recorded writes or page errors. Screenshots retain
narrow/wide Build, Declaration, failure/retry and member states. These use isolated
synthetic data and a production-shaped local presentation overlay; they are not
production measurements. The fixture blocks outside network access, so unavailable
external branding/assets in screenshots are not proof of production asset failure.

The build retains its existing large-entry advisory. No entry split was added.
The artifact entry is `index-D5GEPsWM.js`, SHA-256
`8be3fc7069dfbba674728f1a277ac1aca446aa6d74237ec10a5806ec785cbb30`.
The complete source/artifact manifest is retained locally for coordinator binding.

Initial failures are retained: missing/incorrect new test fixture assumptions,
an unused test variable caught by TypeScript, a sandbox layout launch refused
before fixtures started, and a private mutant harness initially missing the React
plugin. An optional legacy `test:layout` launch also stopped before any fixture
because this worktree has no private `.venv`. Its protected default port and child
TMPDIR omissions were then identified by source inspection; the parent directed
that it remain unrun rather than modify that accepted harness. The required
density and same-look suites above completed using their isolated runner. None is counted as a successful gate or mutant kill.

## Compatibility and limits

`api.ts` is byte-equal to main. Source review compares the live backend source
`e4f9574ca6243fa4a6c3bf33c70acfb662c0f61f` with this base: their HTTP routes
and schemas are unchanged; only two generated announcement text strings differ.
The queue uses the existing revision/mark-revision roster-filler PATCH and existing
Declaration extras response. The remaining accepted changes use existing routes
and response fields while changing words, navigation, confirmation, presentation,
images and refresh scheduling. This is source compatibility evidence, not live API
or Discord delivery evidence.

No performance campaign was repeated for the integrated batch. PR193's original
measurements and limits remain: Build missed its performance targets, while its
final My signups date-present scenario measured CLS 0.0466 locally. Those numbers
must not be attributed to this newly integrated artifact without measurement.
All existing review previews and their data remain intact. Deployment requires
separate integration/coordinator review and the authorized frontend release gates.
