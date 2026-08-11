# Clash of Cards visual boards and artwork

## Asset decision

Card artwork and optional visual boards must be reproducible without runtime
hotlinks. Individual card editors, optional collection overviews, public
proposals, and DMs must still work after member screenshots are discarded.

Three sources were checked on 2026-08-10:

1. Supercell's official fan kit contains useful troop artwork, but a direct
   search did not return Meteor Golem and it was not verified as a complete
   60-card source.
2. Clash Ninja displays all 60 entity icons, but its Terms of Use say site
   content may not be reproduced without written permission. Its icons must
   not be bundled or hotlinked here.
3. [ClashKing Assets](https://github.com/ClashKingInc/ClashKingAssets)
   explicitly welcomes use of its public asset set with credit, publishes the
   files in a GPL-3.0 repository, and contained every catalog image.

The accepted set is pinned to ClashKing Assets commit
`5cb07086e6306331bf21d8a755a6a2c38bc4c205`. The 60 checked-in WebP files are
verbatim upstream bytes totaling 934,520 bytes. Their source paths and SHA-256
hashes are in `assets/cards/NOTICE.md`; the upstream GPL text is copied beside
them. `bb_baby_dragon` intentionally shares the upstream `baby_dragon` icon,
and the local `rubble_witch` label maps to upstream `ruin_witch`.

This does not relicense the bot repository or Supercell's underlying
intellectual property. Supercell's Fan Content Policy independently governs
use of the game artwork. The source files are not cropped, recolored, or
re-encoded. Rendering only scales them in memory to fit a tile, and every
generated image carries the required unofficial/not-endorsed notice. The bot
must remain a non-commercial fan guide/coordinator and must not imply Supercell
endorsement.

Sources:

- <https://fankit.supercell.com/clashofclans>
- <https://www.clash.ninja/cards>
- <https://www.clash.ninja/terms-of-use>
- <https://github.com/ClashKingInc/ClashKingAssets>
- <https://supercell.com/en/fan-content-policy/>

## Renderer contract

`utils/card_board.py` is pure Pillow code with no Discord, network, or database
dependency.

- `render_inventory_card_board(values, player_name=...)` renders the optional
  full collection overview. It uses bundled artwork and a bounded 32-board LRU
  cache; the compact dashboard and individual editor do not need this render.
- `render_card_board(values, artwork_by_card_id=..., player_name=...)` is the
  uncached/custom-art path.
- `render_card_thumbnail(card_id, state)` is the cached 256px card used by the
  interactive category browser. It supplies a category frame, gray/X missing
  treatment, `x2+` spare badge, or `?` possible-spare badge.
- `render_trade_strip(wanted_id, offered_id, other_offer_ids, ...)` makes a
  compact same-category proposal image with at most three alternatives.

All return immutable result records containing PNG bytes, a filename, and
accessible alt text. Missing or invalid state is always **unknown**, never
owned. The optional full board is one 1120 x 1580 PNG: six columns in canonical game
order, four colored category totals, a state legend in its header, gray/X
missing frames, yellow `x2+` confirmed-spare badges, yellow `?` possible-spare
badges, and gray `!` unknown-ownership markers. The proposal strip is
1120 x 360. No source asset is changed on disk.

The scanner's `duplicate_badge_unverified` warning does **not** mean ownership
is unknown: the colored portrait proves the card is owned, while only a hidden
spare badge remains uncertain. Command code represents that exact state as
`owned_spare_unverified`. It counts toward collected/category totals, retains
the category-colored frame, appears in `spare_unverified_card_ids`, and is
reported as a possible spare to check. Only genuinely unresolved ownership is
`unknown`; it does not count as collected. The renderer also accepts the legacy
aliases `owned_unverified` and `spare_unknown`, but new integrations must emit
`owned_spare_unverified`.

Pillow's bundled default font does not cover arbitrary Unicode. Visual copy is
therefore ASCII-only and dynamic display names replace unsupported characters
with `?`; the alt text preserves the original Unicode name. Do not reintroduce
Unicode bullets, dashes, or emoji without bundling and licensing a suitable
font.

On the development workstation, a warm-process 60-card board took 0.290376
seconds on its first render and 0.000030 seconds on an identical cached call;
the rendered PNG was 692,274 bytes. These are measurements, not deployment
guarantees. Rendering is CPU-bound and command code should keep first renders
off the event loop.

## Discord interaction model

Discord media and thumbnail components are static; card artwork itself cannot
be the interaction target. Discord also limits a Components V2 message to 40
component nodes, so 60 interactive card tiles cannot fit in one native message.
The production browser therefore shows four cards per page, each as a Section
thumbnail followed by direct **-1**/**+1** buttons. Two rows of category chips,
four cards, and page navigation total 38 component nodes. The large board
remains a read-only overview under More.

Discord button backgrounds use fixed platform styles and cannot accept custom
hex colors. Category chips therefore use colored markers, while the selected
Container accent and every rendered card frame use the sampled in-game colors:
Elixir `#DB4EE1`, Dark Elixir `#9424B5`, Builder Base `#4D91E5`, and Super
Troop `#F16F2F`.
