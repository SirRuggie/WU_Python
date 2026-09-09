# FWA points monitor

`extensions/tasks/fwa_points_monitor.py` scrapes points.fwafarm.com for each
watched clan's Win Calculator verdict — who is predicted to win the current
FWA war and whether the opponent is itself an FWA clan — and stores the
result in `mongo.fwa_points` so `/todo`'s War view can show it next to a
clan's header (see [todo-dashboard.md](todo-dashboard.md)).

## Deploy history: why this shipped disabled, and isn't any more

points.fwafarm.com sits behind Cloudflare, which hard-blocks requests from
datacenter IPs. Confirmed from the Hetzner box on 2026-07-11: curl returned
HTTP 403 on all three attempts, and because curl has a completely different
TLS fingerprint than aiohttp yet was blocked identically, the block was on the
datacenter IP itself, not the client or the request headers (the exact same
headers returned HTTP 200 from a non-datacenter IP). The feature shipped with
`DEFAULT_ENABLED = False` so `/fwa points` degraded to showing the link — the
pre-existing behavior — rather than silently never populating.

Since 2026-09-08 the bot runs on **Ruggie's Zone**, a residential machine, and
the site answers normally from it with the same headers. `DEFAULT_ENABLED` is
now `True`, but the Mongo `fwa_points` config doc is only seeded with the
default on first boot — an existing database that was seeded while this
shipped disabled needs `/fwapoints enable` run once.

Do not reach for a Cloudflare-bypass library if this ever regresses: those
defeat TLS/JS challenges, not IP-reputation blocks, so they would not help
with this specific block.

## The watch list

The **effective watch list** on every detector tick is:

1. Every clan of type `FWA` in `mongo.clans` (tag sanitized, name from the
   document) — the source of truth for FWA membership. Clan-type membership
   can change at any time without anyone touching `/fwapoints`, so this is
   resolved fresh on every tick rather than cached.
2. Plus the config doc's `watch_list` array, as **extras** — clans outside
   `mongo.clans` type FWA that should still be watched (added via
   `/fwapoints watch-add`, removed via `/fwapoints watch-remove`).

The two are merged and de-duplicated by tag; a clan-type entry wins over an
extra with the same tag. `/fwapoints status` shows the effective list and
marks each entry `[FWA clan]` or `[extra]`.

## How catch-up works

Unchanged from the original design: a cheap **detector loop** (every 10
minutes) asks the CoC API whether a watched clan has an active/preparing war
and, if so, whether it is a war we have not already stored a verdict for. If
so, it starts a **catch-up task** that polls the points site every 2 minutes
(up to 45 minutes) until the page shows that war's opponent and a readable
war number newer than the one on file — the hard gate against writing a
stale verdict for a same-opponent rematch.

Once caught up, the catch-up task also fetches the **opponent's** points page
(same URL pattern, same headers, same timeout) and reads its `Active FWA`
field. A failure there (timeout, non-200, missing field) stores
`opponent_active_fwa: None` and logs once — it never fails the catch-up
itself, since the opponent's FWA status is supplementary to our own verdict.

## Stored record (`mongo.fwa_points`, `_id` = our sanitized clan tag)

| Field | Meaning |
|---|---|
| `clan_name`, `our_clan_tag` | Our clan. |
| `scraped_opponent_tag`, `coc_opponent_tag` | Opponent tag as scraped vs. as reported by the CoC API (should match — this is the hard gate). |
| `opponent_name`, `opponent_name_scraped` | The opponent's name as scraped (both keys carry the same value; `opponent_name` is the one `/todo` reads). |
| `opponent_active_fwa` | `True`/`False` from the opponent's own page, or `None` if that fetch or field failed. |
| `war_number`, `sync_number` | From the Win Calculator block. |
| `point_balance`, `active_fwa` | Our clan's own Point Balance / Active FWA fields. |
| `raw_verdict` | The full text of the verdict line, e.g. "Edrag Rush should win by points (10 > 9)". |
| `predicted_winner_name` | The clan name bolded in the verdict. |
| `our_outcome` | `"win"` if the bolded name matches our clan, `"lose"` if it matches the opponent, else `"unknown"`. |
| `last_war_state` | The site's own "Last Known War State" field. |
| `coc_war_key` | `f"{opponent_tag}:{preparation_start_time.raw_time}"` — identifies the CoC war this record is for. |
| `coc_war_end_time` | ISO string of that same war's `end_time`, from the CoC API. This is what `/todo` compares against `Row.ends_at` to decide whether the record still matches the war being rendered. |
| `scraped_at`, `attempts`, `status`, `last_attempt_*` | Bookkeeping — see the retry/cooldown logic in the module itself. |

## Commands (`/fwapoints`, ADMINISTRATOR-gated)

- `enable` / `disable` — flip the Mongo config flag; `disable` also cancels
  any in-progress catch-up retries.
- `watch-add <tag> <name>` / `watch-remove <tag>` — manage the **extras** only;
  a clan of type FWA in `mongo.clans` does not need to be added here.
- `status` — detector/startup-recovery state, active retries, and the
  effective watch list with each entry's last stored verdict (or "no data
  yet").

## What is NOT available

- **No blacklist marker.** The site carries no "this clan is blacklisted"
  field before a war starts, and this monitor does not attempt to infer one.
- **No ChocolateClash (cc.fwafarm.com) association.** That site is
  Cloudflare-blocked with no API and is not fetched by this monitor or by
  anything else in the bot (see the FWA-sites-access memory note).
