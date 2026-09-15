# `/todo` end-to-end audit — 2026-09-15

## Result

The audit found and repaired four independent correctness defects:

1. Successful automatic checks could skip the Discord edit when task data was
   unchanged. Mongo recorded the check, but the visible `Updated` time remained
   old.
2. War and CWL rows trusted an API phase after its UTC deadline had already
   passed, allowing text such as `ends 2 hours ago` to remain actionable.
3. Recent-clan discovery verified that a requested clan participated in a war,
   then searched both sides for the player. A player found only on the opponent
   side could therefore inherit the requested clan's label and obligation.
4. During a CWL round transition, an expired previous round still labelled
   `inWar` could displace the newly drawn preparation round. The expired row was
   later filtered, producing a false empty result.

The repaired flow publishes every successful scheduled check, reconciles war
phases with their UTC boundaries, restricts membership to the selected war
side, and ignores an expired prior CWL round when choosing the current round.

## Verification matrix

| Area | Evidence | Result |
|---|---|---|
| Raw API deadline to Discord | `test_api_deadline_epoch_reaches_the_rendered_discord_timestamp_exactly` parses an official `/currentwar`-shaped dictionary with `coc.ClanWar`, assembles the War view, renders the panel, and asserts the exact API epoch in `<t:...:R>` | Pass |
| War start/end boundaries | `test_parsed_preparation_start_reaches_render_and_expired_battle_is_removed` verifies a parsed preparation start reaches the final panel exactly and a parsed past-end `inWar` payload produces no actionable row | Pass |
| Full load path | `test_load_pipeline_preserves_preparation_start_timestamp_to_render` exercises links, player lookup, all view builders, and dashboard rendering for a battle starting in 30 minutes | Pass |
| Clan/war association | `test_stale_candidate_cannot_claim_player_found_only_on_opponent_side` parses a real coc.py war model and proves a stale candidate cannot claim a player present only on the opposing side | Pass |
| CWL transition | `test_cwl_transition_does_not_let_expired_previous_round_hide_new_preparation` supplies newest preparation and expired previous `inWar` payloads and requires the preparation round to win | Pass |
| UTC handling | `test_coc_utc_timestamps_do_not_use_the_host_timezone` checks naive API UTC values under UTC, New York, Kolkata, Tokyo, and Auckland host time zones, plus an aware non-UTC value | Pass |
| Raid behavior | `tests/test_todo_raid.py` covers weekend boundaries, unstarted-to-started cache transition, ended and missing entries, 403/error distinction, mixed clans, and earned bonus attacks | Pass |
| Manual controls and navigation | Dashboard tests cover DM/guild delivery, snapshot reuse and misses, view/page controls, Check now renewal, fallback delivery, and private-view refresh | Pass |
| Automatic scheduler | Tests cover startup single-task ownership, due selection, ten-minute scheduling, successful edit-before-record, failed edit retry, missing messages, Mongo failures, legacy rows, and bounded lifetime | Pass |
| Restart/replacement/concurrency | Tests cover generation CAS, takeover/demotion, stale generations, rapid clicks, manual/automatic edit ordering, and three lock contenders | Pass |
| Component routing and startup discovery | Component action/dispatch lifecycle tests and startup discovery tests include `/todo` and its handlers | Pass |

Independent focused command:

```text
.venv/bin/python -m pytest -q tests/test_todo_end_to_end_audit.py tests/test_todo_cache.py tests/test_todo_sessions.py tests/test_todo_dashboard.py tests/test_todo_raid.py tests/test_todo_clan_history.py tests/test_startup.py tests/test_component_dispatch_lifecycle.py tests/test_component_action_names.py
150 passed in 6.75s
```

`git diff --check` also passed.

## Runtime evidence and limits

Read-only service logs showed the deployed process repeatedly completing one
automatic check while reporting `edited=0 unchanged=1`. That confirms the
scheduler was alive and isolates the stale visible clock to the old
edit-suppression behavior. The running process observed during the audit still
used the old code; this audit did not deploy or restart production.

The reported future countdown of roughly two hours when the game showed roughly
30 minutes cannot be attributed to Discord relative-time rendering or the local
120-second active-war cache. The code now proves that an official payload's raw
timestamp reaches the rendered epoch unchanged and fixes one concrete wrong-war
association route. A live affected payload was not available, so the audit does
not claim which of the previous UTC conversion defect, wrong-side association,
or upstream payload caused that particular observation. If it recurs after
deployment, capture the official response's clan tag, war type, state,
`startTime`, `endTime`, parsed epochs, and current UTC time for direct comparison.

The repository-wide suite contains 2,178 tests. A broad run reached about 9%
without a failure, then spent more than 90 seconds in unrelated image-heavy card
tests and was stopped. The bounded `/todo`, component, and startup suite above is
the completion gate used for this change.
