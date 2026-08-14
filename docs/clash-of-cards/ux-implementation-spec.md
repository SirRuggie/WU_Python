# Cards UX implementation spec — final

Status: **Implemented in the repository 2026-08-14** (deployment not
independently verified). Produced against repository commit `3c48b2d` after
the correctness bug pass; implemented the same day with three owner-frozen
decisions — S5 superseded by the full removal of the freshness-confirmation
concept, S7 footer removal applied, S8 left unchanged (**Ask to swap**
stays). Where the implementation deviates in detail, current code and
`tests/test_cards_ux.py` are authoritative.

Owner direction: **Markdown/Text Display hierarchy first → compact semantic
callouts second → additional large Containers only when structurally
necessary.** Screens follow STATE → WHAT CHANGED → WHAT DO I DO, in short
literal international English, mobile first.

---

## 0. Verification baseline

- Verified at `3c48b2d`. The 2026-08-14 bug-pass fixes (Not yet/Not now gates,
  swap integrity, cancellation truth, gem replay guards, family fail-close,
  Ready-only supply, multi-option accept chooser, accepted-trade identity, FWA
  and Noahs Ark regions, gem wording, seven-day copy, sticky rewrite) are all
  present. None are re-reported here.
- **Correction to the tasking:** the pinned stack is **hikari 2.3.5 +
  hikari-lightbulb 3.0.3** (deliberate, documented in `requirements.txt` and
  `docs/hikari-lightbulb-versions.md`), not hikari 2.4.1. This does not hurt:
  see §1.
- Confirmed still open in current code:
  - Scanner failure translations still demand two rows
    (`cards.py:1823-1824`, fallback at `:1857`) while one complete six-card
    row is valid. (known-issues #14.)
  - `AUTO_DEDUCT_DETAIL_MOVED` says "open /cards, tap the card"
    (`cards_deadlines.py:53-54`). The current dashboard has no tappable card —
    the board is one image. Stale control reference.
  - The accepted-trade DM is three stacked Containers — green body + large red
    FWA card + large blue Noahs Ark card (`cards.py:6214-6303`). This is the
    shape the owner rejected.
  - Semantic accent drift (details in §3): `_notice()` hardcodes red even for
    successes (`cards.py:404`, e.g. "Collection Saved" `:3039`);
    `_trade_feedback()` hardcodes green even for "Trade cancelled" and "Trade
    needs review" (`:7239`); My trades is always red (`:6768`); Find
    trades/holders turn red merely because a list is empty (`:4443`, `:4670`);
    the scan upload prompt and progress are red (`:1535`, `:1731`) although
    nothing is wrong.

---

## 1. Capability ground truth

Five layers, kept apart as ordered:

| Layer | Fact |
|---|---|
| **Discord platform** | There is **no native "callout" component**. The only colored primitive is the Container accent bar. Components V2 allows Text Display, Section (1–3 Texts + Button/Thumbnail accessory), Separator, Media Gallery, File, Action Row — nested in a Container **or at message root** (text outside any box). Markdown in Text Display: `# ## ###`, bold, inline code, `-#` subtext, lists, masked links, mentions, timestamps. 40 components/message, 4000 chars across Text Displays, 25 options/select. |
| **hikari 2.3.5 (pinned)** | **Everything above is fully buildable.** V2 landed complete in hikari 2.3.0; nothing V2 changed through 2.5.0 (`docs/components-v2-in-hikari.md`, verified against hikari source at both tags). Thumbnail is legal only as a Section accessory. Containers cannot nest Containers. The V2 flag is auto-set on the GatewayBot path. Modals are **text-input only** — no Label builder exists at any hikari version, so selects/text-display/file in modals are unreachable. |
| **Current WU helpers** | All needed builders are already imported and in use. Shared shapes today: `_trade_dm_container` (DM skeleton), `_notice` (error panel), `_trade_feedback` (action feedback panel). No callout helper exists yet. |
| **Desired design** | The three-tier callout ladder in §2, applied over one main Container per screen. |
| **Needs hikari 2.5 / helper work** | **Nothing in this redesign.** Zero items are blocked by 2.3.5. Items that stay unbuildable **even at 2.5.0**: any select or Label inside a modal (would need hikari to implement Label, or hand-rolled REST payloads — out of scope). Do not upgrade hikari in this pass. |

---

## 2. The callout ladder (core shared pattern)

Discord has no small colored chip, so "compact semantic callout" must be
composed. Three tiers, cheapest first — always pick the lowest tier that works:

- **Tier 1 — inline callout** (default): an emoji-led bold line inside the
  screen's main Container, after a Separator when it starts a region.
  `⚠️ **FWA — Wait for war**` + one short sentence. Cost ≈ 0 extra
  components. No color — the emoji + bold words carry the meaning, which the
  accessibility rule requires anyway.
- **Tier 2 — quiet line**: `-#` subtext (masked links render inside subtext).
  For optional help that must be visually quieter than everything else.
- **Tier 3 — compact accent callout**: a second Container holding **exactly
  one Text Display of at most two short lines** — no `##` heading, no
  Separator, no footer, no buttons. The accent bar is the point. Cost: 2
  components. Reserved for the cases where color classification genuinely
  pays (FWA red warning).

Hard rule: **one large Container per screen.** A different semantic role never
justifies a second large Container; it gets Tier 1, Tier 2, or Tier 3.

---

## 3. Semantic accents (canon)

| Accent | Meaning | Notes |
|---|---|---|
| Red | warning / stop / destructive decision | FWA wait-for-war; real failures; "was it cancelled?" |
| Gold | the player must answer or pay | swap confirm gate, check-in, gem confirm, paused screen, scan upload waiting on images |
| Green | success / confirmed | trade accepted, card sent, saved |
| Blue | optional info / help | sticky, walkthrough |
| None | routine status, lists, navigation, terminal FYIs | dashboard, My trades, empty lists, expired/closed notices |

Color is never the only signal. Terminal states get **less** weight, not more.

**Normalization list (all verified in current code):**

1. `_notice(title, body, accent=…)` — add the parameter; default **neutral**;
   red only for genuine failures. Successes routed through it ("Collection
   Saved" `:3039`, "Possible spares checked" `:2925`, "Duplicate checks
   complete" `:3469`) become green or neutral.
2. `_trade_feedback(…, accent=…)` — same change; "Trade cancelled" → neutral,
   "Trade needs review" → red, accept/complete stay green (`:7239`).
3. My trades container red → **none** (`:6768`).
4. Find trades red-when-empty → none; holders red-when-empty → none
   (`:4443`, `:4670`). Empty is not a warning.
5. Scan upload prompt and "still need more" progress red → **gold** (player
   action required; nothing is wrong) (`:1535`, `:1731`). Real capture
   failures stay red.
6. Demand view gold → none (`:3852`) — it is a list, nothing is required.
7. "Still accurate" button SUCCESS → SECONDARY (`:2501`) — see S5.

---

## MUST CHANGE NOW

### M1. Accepted-trade DM (`_accepted_trade_dm`, cards.py:6214)

1. **Problem:** three stacked Containers (green + big red FWA + big blue Ark),
   ~20 rendered lines plus a decorative footer image. Prose next-step
   paragraph. The owner rejected this shape.
2. **Copy** (move-needed variant):

   ```
   ## ✅ Trade accepted
   **You give:** ⚡ Electro Titan
   **You receive:** ☄️ Meteor Golem
   **Your account:** brilliant31508 · `#YURL2QVJJ`
   **Trading with:** @SirUwU · Sir UwU · `#9LRVV8G8` · [Open their clan](…)

   **Next:** Move to the same clan. Then send the cards in game.
   Then open /cards and tap **I sent my card**.

   -# ℹ️ Need a place to trade? [**Open Noahs Ark**](…) · `#8VPQCR2R`
   -# Your card is reserved until you confirm.
   ```

   Same-clan variant: `**Next:** Send the cards in game.` and no Ark line.
   The clan-name pair ("you are in X, they are in Y") stays available inside
   the **Next** line when clans differ:
   `**Next:** You are in Morning Woods. They are in Edrag Rush. One of you
   moves, then send the cards in game.` (three short sentences, no comma
   splices).
3. **Structure:** ONE green Container: Text (title) · Text (label block) ·
   Separator · Text (Next block + quiet lines). FWA, when relevant, is a
   **Tier 3 compact red callout** appended after the main Container:

   ```
   ⚠️ **FWA — Wait for war**
   Do not trade until war starts.
   ```

   One Text, two lines, nothing else in it. Noahs Ark loses its Container
   entirely and becomes the Tier 2 subtext line above (different-clan trades
   only, same condition as today). Drop the footer image.
4. **Accent:** main green; FWA callout red; Ark none (subtext).
5. **Buttons:** none (unchanged — the confirm action stays in /cards; a DM
   confirm button remains the separately-recorded future idea).
6. **Mobile:** ~11 lines vs ~20+. The "Anyone can join" operational claim is
   dropped rather than reverified. Account identities kept (settled
   self-contained-handoff rule) but exactly one line each.

### M2. Holder acceptance feedback (`_perform_trade_accept`, cards.py:11397)

1. **Problem:** one ~6-sentence paragraph mixing partner, reservation, clan
   state, instructions, DM delivery, and an inline FWA sentence — a second,
   divergent FWA presentation.
2. **Copy:**

   ```
   # ✅ Trade accepted
   **You give:** ☄️ Meteor Golem
   **You receive:** ⚡ Electro Titan
   **Trading with:** @user · brilliant31508 · `#YURL2QVJJ` · Morning Woods

   **Next:** Send your card in game.
   Then open **My trades** and tap **I sent my card**.
   -# The exact cards are reserved. I told them by DM.
   ```

   Move-needed: `**Next:** Move to the same clan. Then send your card in
   game.` DM failure: `-# I could not DM them. Please ping them.`
3. **Structure:** the existing `_trade_feedback` panel body, restructured to
   label lines; FWA when relevant appends the **same Tier 3 callout builder
   as M1** (one canonical FWA presentation, two call sites).
4. **Accent:** green; FWA callout red.
5. **Buttons:** unchanged (**My trades**, **Collection**).
6. **Mobile:** no "Your account" line — this panel replaces the screen the
   holder just acted from, so context binds the account; the title `# Trade
   accepted` matches the requester DM word-for-word (canon).

### M3. Scan complete / needs review (`_scan_review`, cards.py:1995)

1. **Problem:** owner-confirmed wordiest screen. Partial case stacks: stats
   block, "nothing saved" subtext, status block, "Still to check" block, a
   four-line explanation of **Save confirmed cards**, buttons, expiry. Counts
   appear that do not change the decision.
2. **Copy** (partial case — the common one):

   ```
   # Scan complete
   **Preview Member** · `#PREVIEW`
   **I read 12 of 60 cards.** Nothing is saved yet.

   **Still to check: 48 cards**
   - Rows 3–10: Wall Breaker → Meteor Golem

   **Save confirmed cards** saves the 12 cards I read.
   Then set the rest in **Update collection**.
   [Save confirmed cards] [Update collection] [Cancel]
   -# Nothing was guessed. A category with unchecked cards is not ready to trade.
   -# This review is open until 21:14 (in 18 minutes).
   ```

   Full-save case: `**All 60 cards were read.** Nothing is saved yet.` +
   `**52 collected** · 8 missing` + `[Save collection] [Cancel]`.
   Correctable case keeps the one-card fix row:
   `**Fix 3 uncertain cards, then save.**` · `## Next: Balloon` ·
   `[Missing] [Have 1] [Duplicate]`.
   Reserved case: `**Finish or cancel your accepted trade first.**` (one
   line).
   Cut entirely: the privacy sentence (it stays on the upload prompt, said
   once), "It changes nothing else", collected/missing counts on partial,
   duplicate-check count line (asked later by the spares panel anyway).
3. **Structure:** one Container: Text (title+state) · Separator · Text (still
   to check) · Text (do) · ActionRow · Text (subtext). No second Container,
   no footer image.
4. **Accent:** none while reviewing; the existing red stays only for a scan
   that cannot be saved at all (`errors`).
5. **Buttons:** unchanged ids/labels: `Save confirmed cards`,
   `Update collection`, `Save collection`, `Cancel`, and the
   Missing / Have 1 / Duplicate trio.
6. **Mobile:** target ≤ 12 rendered lines for the partial case (from ~20).
   Re-check the 4000-char budget with the worst-case rows list.

### M4. Status DM diet (`_notify_trade_status` + `cards_deadlines.py` strings)

1. **Problem:** every status DM — including terminal FYIs — carries the swap
   line, a detail paragraph, **both** players' account lines, a gold accent,
   and the footer "Run /cards here or in the server for your collection and
   trade status." Owner: repeated account info is clutter; terminal states are
   over-weighted. Plus the stale "tap the card" instruction.
2. **Copy** (shape, expired example):

   ```
   ## Card proposal expired
   ⚡ Electro Titan for ☄️ Meteor Golem
   Nobody answered within 12 hours, so it closed. Nothing changed.
   -# Account: brilliant31508 · `#YURL2QVJJ`
   ```

   Per-message details:
   - **Card arrived** (green): `Sir UwU confirmed they sent it. It is in your
     collection now.`
   - **Cancelled** (none): keep the truthful `_swap_cancel_note` sentences —
     they are load-bearing — nothing else.
   - **Expired** (none): as above.
   - **Auto-deduct, moved** (gold): `The other player confirmed 7 days ago.
     We did not hear back from you, so one copy was removed. Wrong? Open
     /cards, tap **Update collection**, and set your real count.` ← replaces
     the stale "tap the card".
   - **Auto-deduct, no spare** (none): `…Your collection no longer showed a
     spare, so nothing was changed.`
   - **Swap closed, owed side** (none): keep current promise-keeping detail,
     with `open /cards, tap **Update collection**` for the recovery step.
   - **Swap closed, abandoned** (none): current text is already right; trim to
     two sentences.
   - **Needs review** (red): current details kept, they are the warning case.
3. **Structure:** slim variant of `_trade_dm_container`: Text (title) · Text
   (swap line + detail) · Text (`-#` reader account line). No Separators, no
   footer, no footer image.
4. **Accent:** per list above — green arrived, gold auto-deduct-moved, red
   needs-review, none for expired/closed/cancelled.
5. **Buttons:** none (unchanged).
6. **Mobile:** one account line instead of two — a new helper resolves the
   **reader's** role from `recipient_id` (requester and holder discord ids are
   both on the trade) and prints only the reader's own account; the partner is
   already named in the detail where it matters.

### M5. Scanner failure translations (cards.py:1823-1824, 1857)

1. **Problem:** `no_valid_rows` → "did not contain two readable card rows",
   `no_valid_six_column_rows` → "did not contain two complete six-card rows",
   fallback → "could not be validated as the expected two rows". The row
   scanner accepts one complete row; this copy contradicts the valid workflow
   (known-issues #14).
2. **Copy:** `"did not contain a readable row of six cards"` ·
   `"did not contain a complete six-card row"` ·
   fallback `"could not be read as complete six-card rows"`.
3–5. No structure/accent/button change.
6. **Note:** add the missing regression test for this failure copy.

### M6. Semantic accent normalization

The seven-item list in §3, as one batch. Pure parameter/constant changes; no
copy dependencies. (`_notice` and `_trade_feedback` gain an accent parameter
with today's color as the explicit argument at genuinely-red/green call
sites, so no call site changes meaning silently.)

### M7. "Ready to trade" clarity (`_quantity_editor`, cards.py:3121-3124 + `cards_ready`, :10350)

1. **Problem:** owner-confirmed unclear. The status line names the button but
   not the condition or the effect; the feedback line ("Elixir can be traded
   now.") does not say what changed for other players.
2. **Copy:**
   - Not ready: `**Not ready to trade yet.** Check every number. Then tap
     **Ready to trade**.`
   - Ready: `**Ready to trade.** Other players can see these spares.`
   - Feedback after tap (`saved=`): `Elixir is ready to trade.`
3–5. No structure/accent/button change; the label **Ready to trade** stays
   (it is canon across sticky, docs, tests).
6. **Mobile:** unchanged footprint.

### M8. One verb for the card picker (`_quantity_editor`, cards.py:3203)

1. **Problem:** instruction says "**Select** a card below…", the menu says
   "**Choose** a card to edit" — two verbs for one control (same-word rule).
2. **Copy:** `**Choose a card below to change how many you have.**`
3–6. One-word diff; nothing else changes.

---

## SHOULD CHANGE

### S1. Scanner upload prompt + progress (`_scan_upload_prompt` :1528, `_scan_upload_progress` :1686)

- **Problem:** prompt is title + subtitle + intro + 4 bullets + promise
  sentence + linkage/expiry + privacy — and red. Progress repeats the full
  instruction set.
- **Copy** (prompt):

  ```
  # 📸 Send your card screenshots
  **Preview Member** · `#PREVIEW`
  Open your collection in game. Screenshot every row of six cards.
  Send all screenshots here in one message.
  - Any order is fine. Overlap is fine.
  - Do not cut a row at the edge. Five screenshots normally cover all 60 cards.
  [Open collection] [Cancel upload]
  -# Open until 21:14 (in 20 minutes). The bot reads the images once and does not keep them.
  ```

  Progress keeps: matched count line, **Still needed** rows list, `Send only
  the missing rows. Do not resend accepted rows.`, buttons, expiry subtext —
  and drops the re-explained rules.
- **Structure:** one Container each; no change in components beyond dropped
  Text nodes and footer image. **Accent:** gold (see M6). **Buttons:**
  unchanged. **Mobile:** prompt from ~14 lines to ~9.

### S2. Proposal DM trims (`_trade_proposal_dm`, :6114)

- Drop the lead sentence (`**X** wants your Y.`) — the title plus the
  give/receive labels already say it. Keep You/Them identity lines (settled).
- Category subtext → `-# Same-category trade: Elixir for Elixir.`
- Different-clans subtext → `-# You are in different clans. One of you must
  move before trading.`
- No-controls footer → `Open /cards → **My trades** to accept or decline.
  Nothing is reserved until you accept.` Controls footer stays one sentence.
- Accent green → **gold** (a proposal is a question awaiting the reader's
  answer, not a success). Buttons unchanged.

### S3. Gem ask DM + gem confirm (`_gem_ask_dm` :10456, `_gem_ask_confirm_view` :10420)

- Both stay gold (correct: answer/payment required). Compress three
  paragraphs to labeled lines:

  ```
  ## 💎 Somebody needs your help
  **brilliant31508** is missing ☄️ **Meteor Golem**. You have a spare.
  They have no Elixir spare to give back. They pay **40 gems** instead.
  **If you say yes:** post the trade in game — offer your Meteor Golem, ask
  for any Elixir card.
  [Yes, I will post it] [No thanks]
  -# Nothing changes in your collection until you trade in game.
  ```

  Confirm keeps its price-first title (`This will cost you 40 gems`) and gets
  the same 3-line body treatment. Buttons unchanged.

### S4. Check-in DM (`_checkin_dm`, :6947)

  ```
  ## Are you still trading cards?
  Two trade requests for **Name** were not answered.
  **Yes** — your cards stay visible.
  **No** — your cards are hidden. Nothing is deleted.
  [Yes, keep trading] [No, hide my cards]
  -# No answer in 24 hours hides your cards. You can turn them back on any time.
  ```

  Gold, unchanged buttons; body from ~7 lines of prose to 4 short lines.

### S5. "Still accurate" demotion (dashboard, :2499-2505 and :2552-2557)

- **Problem:** owner-confirmed unclear/over-prominent: a green SUCCESS button
  whose three-line explanation sits at the very bottom of the panel, far from
  it.
- **Change:** style SUCCESS → SECONDARY; move the explanation to a single
  subtext line directly under that button row:
  `-# Last confirmed 3 days ago. **Still accurate** saves today's date.
  Trading does not stop either way.`
- **Owner decision:** keep the label `Still accurate` (recommended — canon,
  pinned in docs) or rename to plainer `Still correct`. custom_id
  `cards_confirm` never changes either way.

### S6. My trades polish (`_trades_view`, :6650)

- Accent → none (M6). Empty text →
  `No open trades for this account.` plus a **Find trades** button rendered
  only in the empty state (route exists: `cards_matches:{tag}`), replacing
  the "propose a family-wide swap" sentence (jargon).
- Per-trade summaries already fit the label grammar; keep.

### S7. Retire the decorative footer image (`FOOTER = "assets/Red_Footer.png"`, :146)

- Mounted at the bottom of most Cards panels; costs a Media component and
  real phone pixels on every screen while carrying no information (design
  rule: no components on decoration). **Owner decision** (brand vs space);
  recommended: remove from all /cards panels and DMs; the sticky keeps its
  banner (different asset, informative).

### S8. Trade/swap terminology convergence (**owner decision required**)

Current prose mixes "swap" and "trade" (screens: Find trades, My trades;
titles: "Your swap was accepted", "Finish your swap", "Card swap closed";
button: "Ask to swap"). Recommendation: **trade** becomes the only noun in
prose and titles; "swap" survives nowhere except — pending the owner's call —
the settled button label **Ask to swap** (renaming it to "Ask to trade" is
safe technically, custom_ids unchanged, but it is a settled decision in
ui-decisions.md and must be re-decided explicitly, not drifted).

### S9. Small verified trims

- Holders title `Who Has {card}?` → sentence case `Who has {card}?` (:4569).
- Demand blurb "Worth keeping when you bargain." (idiom-adjacent) →
  `-# Other players need these. Good cards to offer.` (:3847).
- Trade-offer screen accent green → none (:4739) — composing an offer is not
  a success yet.
- Trading-paused body → two lines: `Your cards are hidden. Nobody can send
  you requests.` / `Nothing was deleted.` (:6993-6998).
- Editor scan-block warning → one subtext line:
  `-# Some cards may not be read. Check the result after scanning.`
  (:3297-3299).
- `_swap_sent_view` waiting line stays — the 7-day auto-add promise is
  load-bearing — but drop the em-dash construction:
  `Removed one ⚡ Electro Titan. You have **1** left.`

**Verified as already conforming — no change:** `_swap_confirm_view` ("Finish
your swap": gold, question, Yes/Not yet/No, one-line consequence subtext) ·
`_swap_cancel_check_view` (red, honest cancel notes) · `_swap_sent_view`
shape · account picker · sticky + walkthrough · `_quantity_editor` overall
shape · `_card_focus` · dashboard overall shape · hidden-badge batch review ·
spare-counts panel · admin panel.

---

## FUTURE POLISH

- **F1.** Root-level Text Display outside any Container for the very quietest
  lines (platform supports it; verify hikari builder path + phone rendering
  before adopting; today everything returns `list[Container]`).
- **F2.** "I sent my card" button inside the accepted-trade DM — already the
  recorded future idea in ui-decisions.md; needs ownership recheck + old
  custom_id compatibility. Out of scope now.
- **F3.** Voluntary pause / hide-my-cards entry from the dashboard (recorded
  future feature, product decision pending).
- **F4.** Alt-text pass over the rendered board/strips/thumbnails
  (`card_board.py` already emits alt text; review wording once copy canon
  settles).
- **F5.** Palette accessibility review of exact accent values — GOLD
  `#FFD700` in particular on light theme — required by the design doc before
  the colors are declared final.
- **F6.** Walkthrough/sticky re-shoot after M/S land so step wording matches
  the new screens exactly.

---

## Shared reusable builders (implementation targets)

1. `_callout(emoji, title, line)` → Tier 1 string.
2. `_compact_callout(accent, emoji, title, line)` → Tier 3 Container (one
   Text, ≤2 lines).
3. `_fwa_warning()` → the canonical Tier 3 red FWA callout; call sites: M1
   accepted DM, M2 acceptance feedback. Copy: `⚠️ **FWA — Wait for war**` /
   `Do not trade until war starts.`
4. `_noahs_ark_line()` → the canonical Tier 2 subtext line; call site: M1
   (different-clan only). Copy: `-# ℹ️ Need a place to trade?
   [**Open Noahs Ark**](link) · `#8VPQCR2R``
5. `_reader_account_line(trade, recipient_id)` → `-# Account: Name · #TAG`
   for the reader's role (M4).
6. `_notice(…, accent=None)` and `_trade_feedback(…, accent=GREEN)` grow the
   accent parameter (M6).
7. Label-line grammar constants/docs: `**You give:** / **You receive:** /
   **Your account:** / **Trading with:** / **Next:**` — the one grammar for
   every trade surface.
8. Slim status-DM variant of `_trade_dm_container` (no separators, no footer,
   no image) for M4.

## Canonical terminology

card · collection · spare · category · **Update collection** · **Scan
screenshots** · **Ready to trade** · **Find trades** · **My trades** ·
**Ask to swap** (pending S8) · **Ask for help** (gem path only) · **I sent my
card** · **Still accurate** (pending S5) · **Trade accepted** · trading
on/off, "your cards are hidden" · "reserved" for accepted-trade card locks ·
"Nothing is reserved until you accept." · "row of six cards" (scanner) ·
`2+` = scanner-proven spare, exact count unknown · gems named only on the gem
path, price + payer before commitment. Prose noun: **trade** (S8).

## Preview-harness scenarios to add (`cards_preview.py`)

Existing 19 stay. Add: **20** holder acceptance feedback (M2, both clan
variants) · **21** dashboard (with Still-accurate row visible) · **22**
holders list (with Ask to swap + gem-only variants) · **23** Find trades view ·
**24** My trades list (pending + live + empty) · **25** upload prompt ·
**26** upload progress (partial rows) · **27** editor not-ready vs ready
status lines · **28** notice pair (one success, one failure — accent check) ·
**29** accepted DM same-clan (no Ark, no FWA) for diffing against 3/13.
Scenario 3 already exercises Ark (move_needed, non-Ark clans); 13 forces FWA.

## Blocked by hikari 2.3.5 / gained by 2.5

- **Blocked by 2.3.5: nothing in this spec.** All structures use builders
  shipped since 2.3.0.
- **Gained by upgrading to 2.5.0: zero V2 capability.** The upgrade remains a
  separate coupled move (hikari 2.5.0 + lightbulb 3.2.5) for other reasons;
  never part of this pass.
- Unbuildable at **every** current hikari version (for future reference only):
  selects, Labels, Text Display, or file upload inside modals.

## Repository verification before implementing

1. Tests pin copy: `test_cards.py` (gem-free proposals, seven-day wording,
   board-first payload, component budgets), `test_cards_sticky.py` (wording,
   slang rejection), `test_component_dispatch_lifecycle.py`. Every copy batch
   updates its pins in the same commit.
2. `ContainerComponentBuilder` accent handling for "no accent": confirm
   omitted/`UNDEFINED` vs `None` renders neutral on the pinned build.
3. Component count + 4000-char Text budget re-checked per redesigned screen
   with worst-case data (holders page currently 38/40 — removing the footer
   image buys headroom; scan review rows list at worst case).
4. Mention safety: moved lines that contain `<@id>` keep deliberate
   `user_mentions` behavior (DM sends and channel posts differ today).
5. custom_ids: **none change** in this pass; labels only. Old messages must
   keep working.
6. Deployment state: repo is `3c48b2d`; last independently verified prod is
   `cce2dd2`. Land this pass after (or with) a verified deploy of the bug
   pass, so live screens match one spec, not one and a half.
7. Noahs Ark: the proposed line drops the "open to everyone" claim, so no
   operational reverification is needed; keep tag/link as owner-provided.
8. FWA trigger stays membership-based (clans `type`), never live war state —
   unchanged from current code.
9. Scanner logic and thresholds are frozen: M3/M5/S1 touch **copy only**,
   never `utils/card_scan*.py`.
10. Add this file to `docs/clash-of-cards/index.md` when implementation
    starts.

## Implementation grouping

- **Batch 1 — copy-only, no structure** (lowest risk): M5, M7, M8, M4's
  stale-instruction fixes in `cards_deadlines.py`, S4, S9. Update test pins.
- **Batch 2 — accent normalization:** M6 (+ S1/S2 accent changes), the
  `_notice`/`_trade_feedback` parameter.
- **Batch 3 — accepted-trade cluster:** callout builders (§ Shared), M1, M2,
  preview scenarios 20/29.
- **Batch 4 — status-DM diet:** M4 structure + `_reader_account_line` + slim
  DM variant + preview re-runs 8–12.
- **Batch 5 — scan cluster:** M3 + S1 + preview scenarios 18/25/26.
- **Batch 6 — owner decisions, then apply:** S5 label, S6, S7 footer, S8
  terminology.

Each batch ends with: `py -m pytest tests/test_cards.py
tests/test_cards_sticky.py tests/test_component_dispatch_lifecycle.py`, a
`/cards-dm-preview` sweep, and a phone-width read of every touched screen in
light and dark themes.
