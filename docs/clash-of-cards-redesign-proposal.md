# `/cards` redesign: research & proposal

Research deliverable, 2026-08-10. Eight parallel workstreams plus two
adversarial reviews, findings adjudicated against primary sources.
**No implementation code was written and no existing behaviour was changed.**

Durable stack facts that outlive this proposal belong in
[components-v2-in-hikari.md](components-v2-in-hikari.md) and
[hikari-lightbulb-versions.md](hikari-lightbulb-versions.md). The as-built
description of today's feature stays in
[clash-of-cards.md](clash-of-cards.md) and
[clash-of-cards-visuals.md](clash-of-cards-visuals.md). This file is the
proposal.

Everything measured below was measured on this workstation (Python 3.13,
Pillow 12.3.0) or read out of the `hikari==2.3.5` wheel, not taken from a
changelog. Where a claim rests on Discord documentation rather than source it
says so, and section 9.4 lists what could not be verified at all.

---

# PART 1 — FINDINGS

## 1.1 The problem

The feature has a good renderer and a good screenshot pipeline, and it shows
neither of them on the screen a member actually lands on.

**`/cards` renders zero card imagery.** `_dashboard` (`cards.py:1783`) emits ten
component nodes: a Container with no `accent_color` (`:1912`), a title Text, a
Text carrying `"47 of 60 collected · 13 missing · 6 spares"` (`:1798-1813`), a
Separator, one ActionRow, four Buttons of which three are identical
`SECONDARY` grey (`:1876-1903`), and a footnote. No `Media`, no `Thumbnail`, no
artwork.

**The screen the member wants already exists and is three clicks away.**
`render_inventory_card_board` (`card_board.py:979`) draws a 6-column grid of
category-framed tiles with a duplicate badge and a row of four coloured
category pills (`_draw_category_tabs`, `card_board.py:476-513`), in the true
in-game accents (`CATEGORY_ACCENTS`, `card_board.py:74-79`). It is reachable
only through More, then Full board (`_more_panel:2201`, button at `:2212`), and
that button carries `is_disabled=not complete` (`:2214`), so it is switched off
for exactly the members who have not finished data entry.

**The plumbing to fix that is already written and discarded.** `_dashboard`
takes a `rendered_board` keyword (`:1788`) and the token never reappears in its
body. `_dashboard_view` (`:2751-2755`) does not compute one. `_scan_board_media`
(`:1759`) and `_render_scan_board_async` (`:1775`) are written and referenced
nowhere.

**The real onboarding wall is not a button, it is a gate.** `_editor_ready`
(`cards.py:1945-1948`) returns true only when **all four** categories are in
`complete_categories`, and `_category_browser` hard-returns a `_notice` when it
is false (`:2000-2005`). A brand new member cannot edit a single card until the
whole collection is already marked done. This, not the button layout, is why it
"seems so clunky from the start up".

**Browsing is 4 cards per page.** `CARD_BROWSER_PAGE_SIZE = 4` (`:110`), which is
not a design choice but the 40-node cap divided by the 7 nodes a
Section-plus-Thumbnail card row costs. 19/13/11/17 cards per category is 5+4+3+5
= **17 pages to see 60 cards**.

**Click counts, one linked account, all categories already complete:**

| Task | Clicks today | Path |
|---|---|---|
| See the whole collection with art | 3, and disabled until complete | `/cards` → More → Full board |
| Change one arbitrary card | **7** | `/cards` → Edit cards → chip → Next ×4 → +/- |
| Change one card by name | 5 plus typing | Edit cards → Find card → modal → pick → +/- |
| Propose a trade | **7 interactions plus a second slash command by the holder** | see 1.5 |

**Nineteen distinct screens, 55 registered actions, 8,488 lines.** Five of those
actions are emitted by no builder at all (`cards_scan_confirm_edit:6500`,
`cards_scan_hidden_set:6690`, `cards_scan_hidden_none:6716`,
`cards_hidden_set:7264`, `cards_hidden_none:7282`); each name occurs exactly
twice in the repo, decorator and def. `_quick_update_panel` (`:2271`) and its
nine buttons are reachable only from a "Finish later" on a screen most members
never see. `_review` (`:2732`) has one button, Back, so the good board is a dead
end. `_notice` (`:275`) returns zero buttons, so roughly a dozen error paths
force a fresh `/cards`.

**Two competing icon vocabularies.** `CATEGORY_CHIP_EMOJIS` (`cards.py:118-123`)
uses `🩷 🟪 🟦 🟧` and appears in exactly one place, the four chip buttons at
`:2044`. `CardCategory.emoji` (`utils/cards.py:92-97`) uses `💧 🌑 🔨 ⚡` and
appears in the match views. Neither matches the renderer's `CATEGORY_ACCENTS`,
which is the only place that holds the real colours.

## 1.2 Can we avoid screenshots?

**NO.** There is no supported path to Clash of Cards inventory without
user-supplied input. This was probed live on 2026-08-10, not read off
documentation.

**The official API does not carry cards.** A real 200 response for player
`#Y2R002QPJ` through `https://proxy.clashk.ing/v1`, the same base URL the bot
already uses (`utils/startup.py:78`), has 32 top-level keys and the substring
`card` appears zero times in the whole lowercased payload. Fifty-four
achievements, none card-related. `/cards`, `/events`, `/seasons`,
`/players/{tag}/cards`, `/players/{tag}/events`, `/players/{tag}/collection`,
`/players/{tag}/inventory` and `/clans/{tag}/cards` all return `404 notFound`.
The control probe `/goldpass/seasons/current` returns 200, which proves the
proxy forwards arbitrary paths and those 404s are genuine absence rather than
proxy filtering.

**coc.py 3.10.0 has no card support.** `grep -rin "card" site-packages/coc`
returns two hits, both the word "wildcard" in `ext/triggers/cron.py`. One useful
hedge: `coc/abc.py:66` retains `_raw_data` when `raw_attribute` is set, and
`utils/startup.py:76-83` sets it, so if Supercell ever ships a card field it is
reachable without waiting for a coc.py release.

**ClashKing cannot help, structurally.** `https://api.clashk.ing/openapi.json`
has 47 paths, none matching `card|event|collect|invent`. Their `/json/list`
game-data mirror returns troops, heroes, hero equipment, spells, buildings,
pets, supers, townhalls, translations. Their own spec says stats are collected
by polling the official API, so they cannot expose what the official API lacks.

**The clipboard export is the near miss.** Clash of Clans added
Settings → More Settings → Data Export → Copy in June 2025, which puts a JSON
village snapshot on the clipboard. It carries structure levels and active
upgrades and maps `dataId` to buildings, troops, heroes and spells. It does not
carry cards. The decisive proof is that clash.ninja, the site that built the
paste-your-village import, still says of its own card tracker: tap the cards you
have below to set which ones you have. Manual entry, on the site with the
importer. If the export carried cards they would have wired it on day one.

**An independent implementation reached the same conclusion.** The public
`jcc004/coc` project ships a full card-event feature and its own docs state
there is no API for any of this, that Supercell exposes nothing about the event,
and that every number is typed by hand. Its `docs/api.md` records the same probe
list with the note that these were probed, not assumed.

**In-game sharing is peer-to-peer only.** Supercell's event post describes
tapping the Clash of Cards decoration on another player's village to browse
their collection, and trading through clan chat with both players online. No
share link, no export, no external surface.

**Ruled out as boundary violations, and not recommended:** emulator or ADB
automation, screen-scraping a running client, packet capture or MITM of game
traffic including the reverse-engineered protocol definitions that document
`OwnHomeData`, any private or undocumented Supercell endpoint, and proxying
Supercell ID credentials. All violate Supercell's terms and the boundary this
repo already states for itself (`docs/clash-of-cards.md:6-13`).

### What follows from NO

Since the answer is no, the response is not to keep apologising for the upload.
It is to make **manual entry a first-class peer of scanning rather than a
fallback**, which is exactly what both independent trackers landed on, and which
happens to be the same surface as the display the user asked for. A 60-tile
board you can act on is simultaneously the entry method and the view. Entry and
display collapse into one screen, and the scanner becomes one adapter behind it
rather than the only door.

The single realistic zero-screenshot future is the clipboard export gaining card
fields. Supercell explicitly invited requests for additional export fields. If
that lands, a paste-a-string modal is a drop-in third adapter. Watch it; do not
plan around it.

## 1.3 What Discord can actually render

Verified against the extracted `hikari==2.3.5` wheel (the pinned production
version) unless a row says otherwise.

| # | Capability | Verdict | Evidence |
|---|---|---|---|
| 1 | Container `accent_color` takes a custom hex | **Yes** | `ContainerComponentBuilder` in 2.3.5; already used at `cards.py:1951`, `:2139` |
| 2 | Button background colours | **Five fixed styles only** | 2.3.5 `hikari/components.py`: PRIMARY 1, SECONDARY 2, SUCCESS 3, DANGER 4, LINK 5. `PREMIUM = 6` exists only in 2.4.1+. Arbitrary hex is impossible |
| 3 | Message component cap | **40 total, assume nesting counts** | Discord component reference: "Messages allow up to 40 total components". Not enforced anywhere in installed hikari; `grep` for `MAX_COMPONENT`/`component_count` under site-packages/hikari returns nothing |
| 4 | Action rows per message | **No V2 cap; 6 ship today** | `_category_browser` emits one chip row (`:2050`), four card rows (`:2110`), one footer row (`:2113`) inside a single Container. The legacy five-row limit does not apply under V2 |
| 5 | Select menu option cap | **25** | Discord reference. Every category fits: 19 / 13 / 11 / 17, executed against `CATEGORY_CARDS` |
| 6 | Section accessory | **Button or Thumbnail, exactly one** | 2.3.5 `hikari/components.py:610`: `SectionAccessoryTypesT = Union[ButtonComponent, ThumbnailComponent]`; builder side `hikari/api/special_endpoints.py:2521`. **Artwork can never be the click target, but a Section row can carry a Button** |
| 7 | Media gallery | **1 to 10 items, per-item alt text and spoiler** | Discord reference; `MediaGalleryItemBuilder` in 2.3.5 |
| 8 | Modals | **Text input only** | lightbulb `components/modals.py` exposes only `TextInput`; 3.0.3 is a strict subset of 3.2.1 |
| 9 | Selects per message | **Unknown above 2** | Two coexist today (`cards.py:2652`, `:2671`). No documented cap. Four is an extrapolation. See 9.4 |

### Application emojis on 2.3.5: they exist, and we are not using them

This needs to be stated plainly because it came up as a blocker and it is not
one. The 2.3.5 wheel contains real implementations, not stubs:

```
hikari/impl/rest.py:2681  fetch_application_emoji
hikari/impl/rest.py:2692  fetch_application_emojis
hikari/impl/rest.py:2703  create_application_emoji
```

Discord's emoji resource documentation confirms an application may own up to
2000 emojis, 256 KiB each, usable in any guild and in DMs, and that
`USE_EXTERNAL_EMOJIS` is not required for application emojis. A custom emoji on
a Button is artwork **and** is a click target, which is a genuine correction to
the assumption that artwork can never be clicked.

So a 60-card emoji grid is buildable on the pinned stack today. **We are still
not building it**, for reasons given in section 11. The verdict matters because
it removes the version question from the argument entirely.

### Version upgrade: none required

The class list in `hikari/components.py` is identical between 2.3.5 and the
locally installed 2.4.1. The only enum delta is `ButtonStyle.PREMIUM`, and the
only builder deltas are premium buttons, channel repositioning, pinned-message
iteration and guild onboarding prompts. Components V2 is unchanged across the
two. `docs/components-v2-in-hikari.md:12-14` already records that V2 landed
wholesale in 2.3.0 and that upgrading buys zero V2 capability.

**Nothing in this proposal needs an upgrade, and nothing in it should be gated
on one.** That matters because the only available move is the coupled
`hikari 2.5.0 + lightbulb 3.2.5` jump described in
`hikari-lightbulb-versions.md`, which reopens the rate-limit surface behind
`incident-2026-07-29-channel-rate-limit.md`. Any design that required 2.4+ would
be dead on arrival.

**One correction to file:** `hikari-lightbulb-versions.md:15` says
"`requirements.txt` pins nothing". That is now stale. `requirements.txt:11`
pins `hikari==2.3.5` with a comment explaining the coupling, and pins
`hikari-lightbulb==3.0.3`. Fix that doc separately.

## 1.4 What the renderer can already do, measured

`render_inventory_card_board` (`card_board.py:979`), measured here today:

| Metric | Value |
|---|---|
| Cold render | **0.337 s** |
| Render after a one-card change (warm tile cache, cold board cache) | **0.226 s** |
| Warm board-cache hit | 0.000016 s |
| Output | 1120 × 1580, aspect **0.709**, **710,570 bytes** |
| Cache | `lru_cache(maxsize=32)` at `:966`, keyed on the 60-state tuple |

Two facts about that table drive the design.

**Every edit is a guaranteed cache miss.** The key is the full 60-state tuple
(`:992`), so writing one card invalidates the entry by construction. A design
that puts a board on the landing screen and makes editing the primary loop pays
0.226 s per click, and Pillow's `ImageDraw` holds the GIL so `asyncio.to_thread`
(`cards.py:1768`) buys almost nothing. On a 2 GB box shared with two other bots
this is the one real scaling risk in the whole proposal, and it is addressed in
9.2 rather than waved at.

**Tile art is only a third of the board.** The grid occupies 57% of the canvas
(`GRID_LEFT=70`, `GRID_TOP=218`, tile 150×112, `card_board.py:48`, `:525-529`),
and inside each tile the art box is 136×72 with a name caption below (`:545`,
`:556`), which is 58% of the tile. Art is therefore about **33% of the board
area**. Because Discord scales the image to fit its own box, absolute render
resolution is irrelevant to on-screen legibility beyond a floor. What matters is
only the aspect ratio, which decides whether width or height binds, and the
fraction of the board the artwork occupies.

That reframing settles a disagreement between the two reviews. Growing the
canvas to 1020 × 1816 to fit square tiles makes the aspect **0.56**, taller than
today's 0.709, which under a height-bound client makes tiles *smaller*. The free
win is not a bigger canvas. It is **deleting the per-tile name caption**, which
lets the art box grow from 136×72 to roughly 136×98 inside the existing tile
with no change to board dimensions at all, and deleting the five-clause legend
line at `:912-915` to reclaim header height. Do that first, measure, and only
then consider geometry.

## 1.5 The trade funnel, stage by stage

Single account, all categories complete. Every row is one interaction.

| # | Stage | Surface | Card art | Evidence |
|---|---|---|---|---|
| 1 | Find trades | `_matches_view`, a text digest capped at 10 | none | `:1893`, `:2922`, `MATCH_RESULT_LIMIT` `:91` |
| 2 | Category chip | `_find_category_view`, a select | none | `:2989` |
| 3 | Pick missing card | `_holders_view`, text list up to 20 plus a select | none | `:3047` |
| 4 | Pick holder | `_trade_offer_view`, another select | none | `:3177` |
| 5 | Pick card to give | proposal created, DM plus channel post | strip PNG | `:7703` |
| 6 | Holder receives DM | **plain text, no buttons** | strip PNG | `:4418` |
| 7 | Holder runs `/cards` again, My trades, Accept | 5-per-page list | none | `:4685` |

**Step 1 is a dead end.** `_matches_view` has no trade button anywhere. The
button labelled Find trades does not lead to a trade.

**Step 3 lies.** The view prints up to 20 holders as text but the select skips
any holder with no reciprocal return (`:3070-3072`), so members see twenty names
and can pick four.

**Step 6 is the worst break.** Every trade handler calls `_guild_scope_error`
(`:244`) and then filters on `guild_id: _guild_id(ctx)` (`:7787-7791`), and
`ctx.guild_id` is `None` in a DM, so the notification cannot carry Accept or
Decline. The trade document already stores `guild_id` (`:3313`, `:3536`), so
resolving scope from the trade rather than from the context is a small change
that removes an entire slash-command round trip from the holder's side.

**No family view exists.** The only multi-player surfaces are requester-relative
and capped. Yet `_candidate_inventories` (`:2853`) already loads the whole fresh
family in one indexed query backed by `idx_card_inventories_guild_confirmed`
(`:5776`), and each document already carries all 60 card states plus player
name, clan name and Discord id. Inverting that into `card_id → holders` is one
pass over roughly 500 documents by 60 keys, about 30k dict lookups. The
"running list of who has what" costs **zero new queries and zero new indexes**.
Today that same query runs four separate times to send one proposal.

## 1.6 The scan flow, and what must not be touched

The DM upload works and members like it. It is not being redesigned. Two things
around it are broken and should be fixed in the same pass because they make the
part that works look broken.

**Silent discard.** `_handle_card_scan_dm_upload` does
`if state is None: return` (`:5491-5493`) with no reply. Sessions live 20
minutes (`CARD_SCAN_DRAFT_FOR`, `:103`) and the DM prompt is rewritten only on
success, so a member who takes 25 minutes gathering screenshots uploads into a
prompt that still looks live and hears nothing back. The same silence hits a
corrective re-upload after review opens, because the document's `type` flips.

**The spare interrogation is structurally unbounded.** `_classify_slot` in the
scanner can never return DUPLICATE: every badge-positive path returns OWNED plus
`duplicate_badge_unverified` (`card_scan.py:811-884`). So every spare a player
actually owns arrives as a manual prompt, and `_hidden_badge_review` (`:2453`)
renders **one card per screen**. The repo's own fixture measures the cost:
`tests/test_card_scan.py:749` has 29 owned cards producing 13 unverified. A
near-complete collection trends toward 20 to 30 consecutive prompts, each a
Mongo write and a full re-render.

Batch handlers for exactly this already exist and are dead only because no view
emits their custom ids (`:6690`, `:6716`, `:7264`, `:7282`).

---

# PART 2 — PROPOSAL

## 2.1 The decision

**The board is the app.** Render the collection as one PNG using the renderer
that already exists, put it on the landing screen, and reduce components to a
thin permanent control strip beneath it: four labelled category selects and one
row of buttons. No More menu, no pages, no drilling, no emoji asset pipeline, no
version change.

Three reasons this wins over composing the collection out of components. First,
every pixel of colour, framing and artwork the user asked for is already
achievable in Pillow at the true hex and is impossible in Discord components.
Second, the first shipped commit is a keyword argument that is already plumbed
and thrown away. Third, a select menu holds 25 options and every category fits,
so all 60 cards are one interaction from the first screen with no pagination and
no hidden mode.

## 2.2 The landing screen

`/cards`, one linked account. Nothing is clicked. This is what appears.

```
+- Container(accent_color = 0xDB4EE1) -----------------------------+
| ## Clash of Cards  ·  31d 12h 26m left                           |  Text      [2]
|                                                                  |
| +--------------------------------------------------------------+ |
| |  Wolverine  ·  #Y2R002QPJ                       31d 12h 26m  | |
| |  ,-----------.,-----------.,-----------.,-----------.        | |
| |  | Elixir    || Dark Elix. || Builder B.|| Super Trp.|        | |  Media     [3]
| |  |  19/19  v ||   11/13    ||  11/11  v ||   9/17    |        | |  1120x1580
| |  `-----------'`-----------'`-----------'`-----------'        | |  PNG8
| |   ### ### ### ### ### ###      6 columns, 10 rows             | |
| |   #x2 ### ... ### #x2 ###      frame colour = category        | |
| |   ### ... ### ### ### #x2      ... = grey = missing           | |
| |   ###  ?  ### ### ### ###       ?  = amber = possible spare   | |
| |   ... all 60 cards, art fills the tile, no name captions      | |
| +--------------------------------------------------------------+ |
| **50 of 60**  ·  10 missing  ·  7 spares  ·  updated 2h ago       |  Text      [4]
| [ Elixir · 19/19 complete                                    v ]  |  Row[5] Sel[6]
| [ Dark Elixir · 11/13 · 2 missing                            v ]  |  Row[7] Sel[8]
| [ Builder Base · 11/11 complete                              v ]  |  Row[9] Sel[10]
| [ Super Troop · 9/17 · 8 missing                             v ]  |  Row[11] Sel[12]
| [ Who has what ] [ My trades (2) ] [ Rescan ] [ Switch account ]   |  Row[13] Btn[14-17]
| -# Tap the board to zoom. A spare means 2 or more copies.         |  Text      [18]
+------------------------------------------------------------------+
```

**Node count: 18 of 40.** One Container, three Text, one Media, five ActionRow,
four Select, four Button. `MediaGalleryItem` is counted as zero because it is an
item rather than a component; that is unverified, and at one apiece the total is
still 19.

Each select's options are that category's cards, carrying the state and the
current count:

```
Dark Elixir · 11/13 · 2 missing
  [ ] Minion            ·  none
  [x] Hog Rider         ·  1
  [!] Valkyrie          ·  2 (spare)
  [?] Golem             ·  might be a spare
```

**Every one of the 60 cards is reachable in exactly one interaction from the
first screen.** No chips to press first, no pages, no More menu, no modal.

**First run is the same screen, not a branch.** `render_inventory_card_board`
already accepts unknown states and renders them (`card_board.py:612`), so a
member with no data sees the game screen greyed out and understands the goal
before doing anything. The button row becomes `[ Scan my collection ]` as
PRIMARY plus `[ Switch account ]`, and the four selects still work, because of
the gate deletion below. There is no separate first-run layout to maintain.

**The heart emoji complaint dies by deletion.** There is no category emoji
anywhere in this design. Category colour lives once, in `CATEGORY_ACCENTS`
(`card_board.py:74-79`), and is expressed as drawn pill pixels in the PNG, as
tile frame colour, and as the Container accent. `CATEGORY_CHIP_EMOJIS`
(`cards.py:118-123`) is deleted outright; the four Discord selects carry text
labels with counts and need no glyph. The rival set at `utils/cards.py:92-97`
goes with the views that used it.

## 2.3 Every other screen

There are four, down from about nineteen.

### Focused card, one click from landing

Pick any select option. **Same message, edited in place.**

```
+- Container(accent 0x9424B5) ------------------------------------+
| ## Clash of Cards · Dark Elixir 11/13                           |  Text
| +---- strip: 13 cards at 7 columns, Valkyrie ringed gold -----+  |  Media
| +- Section ---------------------------------+ +----------+      |  Section+Text+
| | ### Valkyrie                              | | 256x256  |      |  Thumbnail (3)
| | Dark Elixir · you have **2**              | | artwork  |      |
| | Tradeable, 2 or more copies               | +----------+      |
| [ None ]  [ Have 1 ]  [ Spare, 2+ ]  [ Back to board ]           |  Row + 4 Btn
| [ Dark Elixir · 11/13                                       v ]  |  Row + Sel
+-----------------------------------------------------------------+
```

**13 of 40 nodes.** The board media swaps to that category's **strip**, which is
the mobile legibility fix arriving for free as a side effect of an action the
member was already taking: a strip is width-bound rather than height-bound, so
it renders substantially larger on a phone than a 10-row board.

Three **absolute** state buttons, not plus and minus. Absolute set removes the
entire increment/decrement/keep family, the disabled-button edge cases at
`:2079` and `:2087`, and the three-interaction quick-update modal chain. The
button matching the current value renders `SUCCESS` green, so state is visible
without reading the sentence. The category select stays mounted, so a member
fixing five cards in one category never leaves: pick, tap, pick, tap. **One
click per card after the first.**

### Who has what, one click from landing

See section 2.6.

### Holders, one click from the family board

One Section per holder, capped at five plus a "+n more" line, each Section
carrying an `[ Ask ]` **Button accessory**. This is verified legal on 2.3.5:
`SectionBuilderAccessoriesT = Union[ButtonBuilder, ThumbnailComponentBuilder]`
(`hikari/api/special_endpoints.py:2521`). One click from seeing a holder to
proposing the trade. Media is `render_trade_strip` (`card_board.py:683`,
0.037 s) showing their card and yours side by side.

This collapses `_holders_view` (`:3047`) and `_trade_offer_view` (`:3177`) into
one screen and removes one full family scan. `holders_for_card`
(`utils/cards.py:478-540`) already computes each holder's exact legal return
tuple; today the second screen only re-renders it.

### Scan review, in DM, otherwise unchanged

Covered in 2.7.

## 2.4 Click counts, before and after

| Task | Today | Proposed |
|---|---|---|
| See the whole collection with art | 3, gated off until complete | **0** |
| Change one card | 7 | **2** |
| Second card, same category | 7 | **1** |
| Find a card when you do not know its category | modal plus typing | **1**, all four selects are labelled and on screen |
| See who has what | does not exist | **1** |
| Propose a trade, requester side | 7 | **4** |
| Holder accepts | second `/cards` plus 2 | **1**, in the DM |

## 2.5 The action surface: 55 to 20

| New handler | Absorbs |
|---|---|
| `cards_board` (tag) | `cards_dashboard`, `cards_more`, `cards_review`, `cards_editor`, `cards_advanced`, `cards_confirm` |
| `cards_pick` (select: tag\|card) | `cards_editor_category`, `cards_category`, `cards_editor_find`, `cards_editor_find_submit`, `cards_quick_modal`, `cards_quick_submit`, `cards_update`, `cards_hidden` |
| `cards_set` (tag\|card\|0\|1\|2) | `cards_editor_inc`, `cards_editor_dec`, `cards_editor_keep`, `cards_quick_apply`, `cards_scan_hidden_yes`, `cards_scan_hidden_no`, `cards_scan_hidden_missing`, `cards_set_missing`, `cards_set_duplicates`, `cards_clear_missing`, `cards_clear_duplicates`, `cards_baseline` |
| `cards_family` (tag\|category) | `cards_matches`, `cards_find_category`, `cards_find_card`, `cards_holder_page` |
| `cards_ask` (tag\|holder\|give_card) | `cards_trade_holder`, plus the second holder screen |
| `cards_scan_fix` (draft\|state) | `cards_scan_fix_missing`, `_owned`, `_duplicate` |
| `cards_scan_end` (draft\|confirm\|cancel) | `cards_scan_confirm`, `cards_scan_cancel`, `cards_upload_cancel`, `cards_scan_retry_cancel` |
| Kept unchanged (7) | `cards_account_page`, `cards_account_select`, `cards_scan_start`, `cards_scan_accounts_retry`, `cards_scan_hidden_later`, `cards_trades`, `cards_scan_hidden_set` (resurrected as the batch spare view) |
| Trade transitions kept (6) | `cards_trade_request`, `_accept`, `_ready`, `_decline`, `_cancel`, `_complete` |

**Twenty handlers.** Each kept trade transition is a distinct guarded Mongo
predicate (`:7797`, `:7900`, `:8090`, `:8175`); merging them would move the
transition name into a payload and lose the per-transition guard, which is a
correctness regression for a two-party workflow. They stay.

**Deleted views**, roughly 1,800 lines: `_more_panel` (`:2201`),
`_quick_update_panel` (`:2271`), `_update_overview` (`:2539`),
`_category_editor` (`:2592`), `_category_browser` (`:1991`), `_card_editor`
(`:2143`), `_editor_search_choices` (`:2162`), `_hidden_badge_review` (`:2453`),
`_matches_view` (`:2922`), `_find_category_view` (`:2989`),
`_trade_offer_view` (`:3177`), `_review` (`:2732`).

**Deleted dead code**, already unreachable: the five orphan handlers listed in
1.1, plus `_hidden_badge_update` (`:7223`) and `_parse_hidden_target` (`:436`).

**One write primitive.** The optimistic-revision guard is copy-pasted verbatim
four times (`:5085`, `:5175`, `:5278`, `:5365`), which is why callers must catch
three different exception tuples in five different combinations. Everything
funnels into `_write_one_card` (`:5043`) with one guard.
`_write_category` survives internally only as the scan commit path. This also
retires the one genuine inconsistency in the current code: `cards_quick_apply`
is the only handler that reads `expected_revision` out of the custom id
(`:2419`, parsed at `:394-409`) instead of the live document, so a stale button
fails closed there and fails open elsewhere. That path dies with the merge.

**Dispatcher: no change needed.** `extensions/components.py:249-259` rewrites
`command_name` from `values[0]` only when the custom id names a group, and
`cards.py` registers no groups. Existing handlers read
`getattr(ctx.interaction, "values", ())` themselves (`:5909`, `:6706`, `:7276`,
`:7340`, `:7587`, `:7671`, `:7714`). Select-driven handlers work as-is.

One cheap unrelated saving worth taking while in here: the dispatcher calls
`get_state` unconditionally (`components.py:276`), and cards packs all state
into the custom id and never uses `button_store`, so every cards click pays two
Mongo round trips that always miss. Skipping the lookup when
`requires_state=False` and the id carries no state prefix removes about two
reads per click across all roughly 120 handlers in the repo, not just cards.

## 2.6 The family "who has what" board

One green button on the landing screen.

```
+- Container(accent 0x00B237) -------------------------------------+
| ## Who has what · Warriors United                                |  Text
| -# 43 collections, all refreshed in the last 72 hours            |
| +-- the same 60-tile board, holder-count badge instead of x2 --+ |  Media
| |  #3   #0   #7   .1   #2  ...   gold ring = you are missing it | |
| |  badge grey when nobody holds a spare                         | |
| +---------------------------------------------------------------+ |
| **You are missing 10.** Seven have a clanmate holding a spare.   |  Text
| [ Ask for a card you are missing (7 available)               v ] |  Row + Sel
| [ Back to my board ]  [ My trades ]                              |  Row + 2 Btn
+------------------------------------------------------------------+
```

**Nine nodes. Zero new queries, zero new indexes.** `_candidate_inventories`
(`:2853`) already returns the whole fresh family in one indexed read; inverting
it to `card_id → holder_count` is a single pass. Render is the same function in
a different mode. Unlike the per-player board, this one caches well, because
family-wide state changes far more slowly than one player's.

This is the surface that beats the game rather than imitating it. In-game
trading needs both players online simultaneously and happens in clan chat. This
list is asynchronous and persistent. That is the honest pitch for why the upload
is worth doing, and it should be visible from the first screen.

## 2.7 Trades

**What changes.**

1. Find trades becomes Who has what. `_matches_view` (`:2922`), the read-only
   digest capped at 10 that has no trade button on it, is deleted.
2. Holder selection and return-card selection collapse into one Section list
   with `[ Ask ]` accessory buttons. `_parse_trade_option` (`:477`) already
   parses the `holder|given_card` composite.
3. **Trade DMs carry Accept and Decline.** Resolve scope from the trade
   document's stored `guild_id` (`:3313`) rather than from `ctx.guild_id`, which
   is `None` in a DM and currently trips `_guild_scope_error` (`:244`) at
   `:7787-7791`. This is the single highest-leverage change in the funnel: it
   removes a whole slash-command round trip from the holder.
4. **Check clans stops being a button members have to press.** `_live_family_clans`
   (`:4218`) is already invoked on accept, ready and complete. A five-minute
   APScheduler sweep over `status: "move_needed"` promotes to `ready` and
   notifies both sides. Keep the button as a manual "check now".
5. **The `needs_review` row gets a way out.** Today it renders as text with no
   buttons at all (`:4661`, and the branch chain at `:4703-4756` has no case for
   it), while `_invalidate_trade_categories` (`:3513`) pulls the category out of
   `complete_categories`, which silently drops the dashboard headline and, today,
   removes Find trades entirely. Give the row one button into `cards_pick` for
   the affected category, and render the `inventory_updates` booleans the bot
   already persists (`:8333`, `:8375`) so it says which side was written instead
   of telling both members to recheck everything.
6. **Drop the 25-slot proposal lease machinery** (`:3376`, `:3394`, `:3406`), and
   `_proposal_slot_reclaimable` (`:3277`) which costs an extra `find_one` per
   existing slot. The unique sparse index `uniq_open_card_proposal` (`:5799`)
   already prevents duplicate proposals. A `count_documents` capped at five on
   the existing requester and holder indexes replaces all of it.

**What stays.** All six trade state transitions with their own Mongo predicates.
Holder pagination at 20 (`:92`), which is justified at 500 players. And
**Trade completed stays a manual button**, because the bot cannot observe the
in-game trade. It is already either-side and one click (`:4750`), which is
correct.

## 2.8 Migration and risk

### Data model: nothing changes, no migration script

`cards: {card_id: 0|1|2}` (`utils/cards.py:21-23`), `inventory_revision`,
`confirmed_at`, `scan_duplicate_unverified_card_ids` and the whole `card_trades`
collection keep their meaning. Two fields change status:

- `complete_categories` becomes **derived** rather than stored: a category is
  complete when every card in it has a non-unknown state. This is what lets a
  day-one member edit anything.
- `reviewed_lists` becomes vestigial when the `cards_baseline` heuristic
  (`:7481-7488`) is deleted. Leave the field in place and ignore it.

### The DM scan flow survives, and gets two bug fixes

`cards_scan_start`, the DM prompt, `_handle_card_scan_dm_upload` (`:5481`), the
partial-capture retake copy in `_scan_upload_progress` (`:1218`, which names
exact rows and is the best copy in the feature) are all untouched. Three
changes, all additive:

1. The review screen gains the board media it already has a renderer for
   (`_render_scan_board_async`, `:1775`, written and currently unreferenced).
2. The 13-to-30 one-card-at-a-time spare prompts collapse into a **single
   multi-select** of the possible spares, which fits under the 25-option cap.
   `cards_scan_hidden_set` (`:6690`) and `_write_hidden_batch` (`:5122`) already
   handle exactly this and are dead only for want of a view.
3. Unverified spares that the member does not resolve are **rendered as a state
   on the board** (an amber marker) rather than queued as blocking prompts. The
   member fixes them whenever, through the same selects. This is the cleanest
   available fix for a problem that is structural: `_classify_slot` can never
   return DUPLICATE (`card_scan.py:811-884`), so the prompt queue can never be
   short.

Two bugs to fix in the same pass, because they make the working part look
broken:

- **Always reply in DM**, even with no live session (`:5491-5493`). "That upload
  window closed, run `/cards` to start a new one" costs one line.
- **Remove the `cards_advanced` escape button offered on a DM failure screen**
  (`:1567-1572`). It routes through `_load_target` and hard-rejects with
  "run this inside the family server", so it is a dead-end button on the failure
  screen. It dies with `cards_advanced` anyway.

### Version upgrade risk: zero, deliberately

Nothing here requires anything absent from 2.3.5. See 1.3. The upgrade track
stays a separate project and this proposal must not be used to justify it.

### Ranked risks

| # | Risk | Severity | Mitigation |
|---|---|---|---|
| 1 | **Full-board legibility on a phone is unmeasured.** 1120×1580 at aspect 0.709 under an unverified client media box | High | **Hour one of the build is a phone measurement.** Parameterise `columns` in the renderer so the fallback is a constant, not a rewrite. Fallback is four stacked category strips, four Media nodes, width-bound and therefore larger |
| 2 | **Render cost with a cache that misses on every edit.** 0.226 s per edit, GIL-bound, on a 2 GB box shared with two bots | High | Drop `optimize=True` (`card_board.py:946`), which costs 0.171 s of the 0.337 s for a 2.5% size saving. Quantise to PNG8, roughly 1.5 MB to 383 KB at 2× artwork. Cache the Discord CDN URL keyed by state hash in Mongo so unchanged re-opens re-reference rather than re-render. **Build the URL cache in the same slice as the landing board, not later** |
| 3 | **CDN URLs are signed and expire** (`?ex=`), so the URL cache needs a TTL and a re-render fallback | Medium | Roughly 20 h TTL, fall through to render on miss. Treat as a build item, not a footnote |
| 4 | **Four selects in one message is extrapolated from two** | Medium | Prototype in slice 1. Fallback is two selects plus a two-button category toggle, 16 nodes, costs one click |
| 5 | **Accessibility is worse than a component grid.** Sixty cards become one image; a screen reader gets alt text only | Medium | `RenderedCardBoard.alt_text` already exists and already lists missing cards. Select option labels carry real card names, so the *actionable* surface stays text |
| 6 | **Egress.** Roughly 400 KB per board view, roughly 6,000 renders across a 500-player event | Low | About 2.4 GB. Acceptable, but someone should see the number before it appears on a bill. The URL cache removes most idle re-opens |
| 7 | **Baked artwork hashes.** `CARD_ARTWORK_HASHES` (`card_scan.py:98`) means a card-set rotation makes every capture fail identity, and the retake loop has no exit | Low, but a cliff | Out of scope here, but the manual-entry-as-peer decision means the feature degrades to usable rather than to broken |
| 8 | **The countdown has no data source.** No API exposes the event end date | Low | Hand-entered constant in config, or omit it. Do not fabricate it |
| 9 | **503 tests currently pass.** The handler cull touches many of them | Low | Budget test repair explicitly in the cull slice |

## 2.9 Build order

| Slice | Ships | Effort |
|---|---|---|
| **0** | **Measure a 1120×1580 media item on a real phone.** This is the only thing that can invalidate the spine, and both fallbacks are already designed | **1 hour** |
| **1 (minimum viable, ship first)** | Compute the board in `_dashboard_view` (`:2751`) and pass it to the `rendered_board` parameter `_dashboard` already accepts (`:1788`). Delete `is_disabled=not complete` (`:2214`). **Delete the `_editor_ready` gate (`:1945-1948`, `:2000-2005`) and derive `complete_categories`.** Delete `CATEGORY_CHIP_EMOJIS` (`:118-123`) and put counts in button labels. Drop `optimize=True` (`card_board.py:946`). Add the CDN-URL-by-state-hash cache | **1 day** |
| **2** | Board restyle: delete the five-clause legend (`card_board.py:912-915`), delete per-tile name captions, grow the art box, grayscale on missing (the desaturate at `:398-400` exists and is unused on the board), move the `x2` badge to the bottom edge, dark background, amber possible-spare state, completion check drawn as a three-point `ImageDraw.line`. PNG8 quantisation | **2 days**, `card_board.py` only, unit-testable |
| **3** | Four labelled category selects, the focused-card panel with absolute state buttons, the unified `cards_set` write primitive with one revision guard | **2 days** |
| **4** | Handler cull 55 to 20, delete the dead views and the five orphan handlers, plus test repair | **1 day** |
| **5** | Family board. The query already exists | **1 day** |
| **6** | Trade collapse, `[ Ask ]` Section accessories, DM Accept and Decline, the `move_needed` sweep, the `needs_review` button | **2 days** |
| **7** | Scan review board media, batch spare multi-select, the always-reply-in-DM fix | **1 day** |

**About ten days total, and slice 1 is one day and carries most of the visual
win.** It answers "it does not look good", "open it and immediately see my whole
collection", "there are so many buttons" partially, and the heart-emoji
complaint, against code that is already written and merely uncalled. Slice 1
plus the gate deletion is also what unblocks a brand new member, which is the
actual root of "clunky from the start up".

Do **not** ship slice 1 without the gate deletion. A beautiful landing screen in
front of a locked door is the same complaint with better art.

## 2.10 What we are not doing, and why

**A 60-card application-emoji grid.** Fully buildable on 2.3.5 (see 1.3), and
rejected anyway. Discord renders inline custom emoji small, so 60 of them is a
status mosaic rather than the game screen: the user's own words are "I have one
of this, two of that, none of these", and demonstratives require identifying the
troop. The proposed escape hatch, that a block of 27 or fewer emoji renders
large, almost certainly does not apply, because jumbo sizing keys on message
`content` and a Components V2 message has no `content` at all
(`components-v2-in-hikari.md:52-56`). Beyond legibility it costs 244 uploaded
assets in a global mutable app-scoped namespace, an undocumented creation rate
limit, a Mongo name-to-id map, a warmed process cache and an owner-only sync
command, all for a seasonal event whose card set rotates. Failure mode is a wall
of black squares; a slow image is recoverable, that is a support ticket. And a
screen reader hears `:k1_07:`.

**Four category application emojis for the chip buttons.** Considered, and
dropped. The colour the user objected to is now drawn in the PNG at the true
`0xDB4EE1`, so a small coloured dot on a grey button beside it adds a second
source of truth for category colour, which is precisely the bug we are deleting.
Text labels with counts are better and free.

**A single category-scoped select instead of four.** It saves six nodes out of
twenty-four spare and reintroduces the complaint: its contents depend on which
chip you last pressed, and a member hunting Valkyrie must first know she is Dark
Elixir. There is no budget reason to pay for hidden modal state.

**Bundling a font.** Pillow's default (Aileron) renders `✓ × • é ★` as identical
missing-glyph boxes, which is real and is why the ASCII guard at
`card_board.py:248` exists. The answer is to draw the completion check as a
short polyline, not to take on a licence question for one glyph.

**Keeping plus and minus.** Absolute `None / Have 1 / Spare` is one write
primitive, one guard, and no disabled-button edge cases. Every button in the
current design maps cleanly onto a target count of 0, 1 or 2.

**Any route to game data that is not user-supplied.** Emulator or ADB
automation, screen-scraping a running client, packet capture or MITM including
the published reverse-engineered protocol definitions, private or undocumented
Supercell endpoints, and proxying Supercell ID credentials. All violate
Supercell's terms and the boundary this repo already sets for itself. The
in-bounds set is: official API reads, ClashKing's public API, the in-game
clipboard export, user-supplied screenshots, and manual entry. None of them
contains card data today.

---

# PART 3 — WHAT COULD NOT BE VERIFIED

Stated plainly, because several of these shape the design.

1. **Discord's client-side maximum media box.** Not documented. Every
   legibility number in this proposal is derived from aspect ratio, not measured
   on a device. This is slice 0 and it is one hour of work.
2. **Whether nested components count toward the 40-component cap.** Discord says
   "up to 40 total components" and separately that a Container holds "up to 40
   child components". Read as one pool, which is the conservative reading. No
   validation exists anywhere in installed hikari 2.4.1: `grep` for
   `MAX_COMPONENT`, `component_count` and `total_components` under
   site-packages/hikari returns nothing, so this is a Discord API-side rule
   only. Today's four-card browser page computes to 36 to 40 nodes and works,
   which is consistent.
3. **Whether a `MediaGalleryItem` counts as a component.** Assumed zero. At one
   apiece the landing screen is 19 of 40, so it does not change any decision.
4. **Whether more than two select menus are permitted in one message.** Two ship
   today. Four is an extrapolation. Docs impose no cap beyond the 40-component
   total, and six ActionRows demonstrably ship in one Container, but neither of
   those proves the select case. Prototype in slice 1.
5. **Application-emoji creation rate limits.** Discord documents only that quota
   figures may be inaccurate and 429s are possible. Moot here, since we are not
   building the emoji pipeline.
6. **Whether jumbo emoji sizing evaluates per component or per message.**
   Undocumented. Also moot for the same reason, and the reasoning in 2.10 stands
   without it.
7. **Scanner CPU on real captures.** Measured at 0.74 s on 18 KB synthetic
   fixtures. Real 1 to 3 MB phone captures are unmeasured.
8. **`hikari-lightbulb-versions.md:15` is stale**, claiming `requirements.txt`
   pins nothing when it now pins both packages with a comment. Fix that file
   separately; it is not part of this work.

---

## Sources

All fetched or executed 2026-08-10 unless noted.

**Primary source read locally**

- `hikari==2.3.5` wheel, extracted: `hikari/impl/rest.py:2681,2692,2703`
  (application emoji), `hikari/components.py:610`
  (`SectionAccessoryTypesT`), `hikari/api/special_endpoints.py:2521`
  (`SectionBuilderAccessoriesT`), `hikari/components.py` `ButtonStyle`
- Installed hikari 2.4.1,
  `C:/Users/shaun/AppData/Local/Programs/Python/Python313/Lib/site-packages/hikari`
- Installed `coc.py` 3.10.0, `site-packages/coc`
- This repo: `extensions/commands/cards.py`, `utils/cards.py`,
  `utils/card_scan.py`, `utils/card_board.py`, `extensions/components.py`,
  `requirements.txt`, `tests/test_card_scan.py`

**Discord**

- Component reference, https://docs.discord.com/developers/components/reference
- Emoji resource, https://docs.discord.com/developers/resources/emoji

**Clash of Clans data**

- Official API through `https://proxy.clashk.ing/v1`, probed live
- Developer portal, https://developer.clashofclans.com/
- ClashKing OpenAPI, https://api.clashk.ing/openapi.json
- Supercell, Clash of Cards event post,
  https://supercell.com/en/games/clashofclans/blog/news/clash-of-cards-event/
- Supercell fan content policy, https://supercell.com/fan-content-policy

**Prior art**

- Clash Ninja card tracker, https://www.clash.ninja/cards
- Clash Ninja swap shop, https://www.clash.ninja/cards/swap-shop
- Clash Ninja, one-tap village updating (June 2025),
  https://www.clash.ninja/blog/one-tap-village-updating-is-here
- Village export field mapping,
  https://gist.github.com/pghant/0717bb1e0e4e0d1373e90bdb3057d9dd
- `jcc004/coc`, https://github.com/jcc004/coc, its `docs/cards.md` and
  `docs/api.md`
- Karuta wiki, cards, https://karuta.wiki.gg/wiki/Cards

**In-repo**

- [components-v2-in-hikari.md](components-v2-in-hikari.md)
- [component-dispatcher.md](component-dispatcher.md)
- [hikari-lightbulb-versions.md](hikari-lightbulb-versions.md)
- [clash-of-cards.md](clash-of-cards.md)
- [clash-of-cards-visuals.md](clash-of-cards-visuals.md)
- [incident-2026-07-29-channel-rate-limit.md](incident-2026-07-29-channel-rate-limit.md)

Card artwork in `assets/cards/` is from ClashKing Assets, GPL-3.0.
