# Clash of Cards tracker

## Why `/cards` owns the data

The August 2026 Clash of Cards event inventory is not present in Supercell's
public Clash API. The in-game village data export is documented for structure
levels and active upgrades; current community trackers still require manual
card entry. Player tags, Clash API tokens, and Discord links can prove identity
or load a player profile, but none of them unlock card counts.

Do not replace this with client automation, emulator taps, packet inspection,
or a private endpoint. Those are both brittle and outside the supported Clash
API surface. The bot intentionally observes only what a member tells it through
the private `/cards` panel.

Sources checked on 2026-08-10:

- <https://supercell.com/en/games/clashofclans/blog/news/clash-of-cards-event/>
- <https://developer.clashofclans.com/>
- <https://www.clash.ninja/cards>
- <https://www.clash.ninja/blog/one-tap-village-updating-is-here>
- <https://supercell.com/en/terms-of-service/>

## Catalog and state

The live event has 60 cards in four fixed sections:

| Category | Cards |
|---|---:|
| Elixir | 19 |
| Dark Elixir | 13 |
| Builder Base | 11 |
| Super Troop | 17 |

`utils/cards.py` is the canonical ordered catalog. The order was checked against
the live six-column collection grid and the current Clash Ninja tracker. Card
ids are stable local slugs; player tag remains the inventory identity.

The bot stores a copy count per card:

- `0`: missing;
- `1`: owned once;
- `2` or more: that many copies, of which all but one are tradable.

`DUPLICATE` is the threshold at which a card becomes tradable, not a ceiling.
Every rule tests `>= DUPLICATE` rather than `== DUPLICATE`, so holding four is
never mistaken for holding none. Documents written before counts existed store
at most `2` and remain valid with no migration: they mean "at least one spare",
which is exactly what they always meant.

The scanner still records the floor. A badge proves a spare exists but the
scanner reads the badge's shape, not the digit inside it, so every spare it
finds is saved as `2` and displayed as `2+`. Only a number a member entered is
shown exactly. Immediately after a scan saves, the bot lists the cards that
came back as spares and offers to set their real counts; skipping is a first
class option, because trading works identically on `2+`.

Exact counts change nothing about matching. The rule is that a card never gives
away its last copy, so two and five are both simply "can spare one". Counts buy
honest display and better family totals, not different trades.

Each inventory is one durable `card_inventories` document keyed by player tag.
`complete_categories` prevents an untouched category from being mistaken for a
fully owned one. Discord id, guild id, player/clan display data, update time,
and confirmation time travel with the card map.

## Member flow

`/cards` is the only slash command. Account selection, setup, later edits,
review, confirmation, and matching are buttons and menus inside its private
panel; there are no separate `/cards scan` or `/cards review` commands. It
reuses the same ClashKing account links as `/accounts`, and every component
mutation rechecks that the clicking Discord user still owns the selected tag.
This is necessary because the shared component dispatcher does not enforce its
`user_only` flag.

`CARDS_GUILD_ID` is the Card Hub's authority boundary. The command and every
component interaction are accepted only when their Discord guild id matches
that configured server id. A narrow exception allows buttons in a private DM
only when they carry a live, account-bound scan session that was created from
the configured server. Other servers, unrelated DMs, and a missing or invalid
`CARDS_GUILD_ID` fail closed before collection or trade data is created or
changed. Server responses remain ephemeral.

Screenshot import is the primary setup path. The bare `/cards` command has no
attachment fields. A member first chooses the Clash account, then taps **Scan
screenshots**. The bot opens a 20-minute account-bound DM session where the
member selects every screenshot once in Discord's normal composer and sends
them together. One to ten PNG, JPEG, or still WebP images are accepted per
message, in any order. Five clean captures with two complete card rows each
normally cover the collection.

The scanner assigns every valid image to its logical section. If coverage is
incomplete, the DM reports the exact missing row range and its first/last card
names. The member sends only those missing images; already accepted sections
are restored from a BSON-safe checkpoint, so no raw screenshot has to be kept
between messages. Duplicate images are ignored without asking for a needless
retake. Image bytes are cleared immediately after each CPU-bound scan. Only the
derived checkpoint, card ids, states, confidence, and warnings live in the
short-lived session.

The scanner validates the fixed category-frame pattern, six-column geometry,
logical page assignment, distinct captures, repeated-row overlap, and a compact
artwork fingerprint for every expected card before binding the ten visible rows to the
canonical 60-card catalog. A catalog change or unexpected artwork therefore
fails closed instead of shifting card identities.

**Fail-closed is per card, not per page.** An earlier build discarded an entire
capture when any portrait failed its fingerprint check, so four unproven cards
out of twelve cost the member all twelve. On a real five-capture import that
left 48 of 60 cards unseen and the collection unusable. A page now keeps every
card that proved its identity and marks only the unproven ones unknown, which
the member is then asked about. A capture is still rejected whole when *no*
portrait on it proves its identity, because that means the page assignment
itself cannot be trusted.

The fingerprint thresholds are a runner-up gap of 8 bits with a distance
ceiling of 46. The gap is the load-bearing test: absolute distance shifts with
device scaling and JPEG recompression, while the ranking does not. On a live
capture set, correct identifications ran 0 to 53 bits from their anchor while
the nearest wrong card in the same category sat a median 34 bits further out.
The ceiling cannot be raised past 46, because the two closest same-category
anchors are 47 bits apart and anything at or above that could fall inside the
wrong card's radius; `test_artwork_anchor_catalog_is_complete_private_and_separated`
pins this. Missing portraits are
detected from the grayscale artwork. Badge recognition has not yet been
validated broadly enough across devices and `xN` variants to authorize trade
supply. Neither a possible yellow badge nor a badge covered by the reward track
is therefore promoted automatically. The safe minimum is **owned once**, and
those card ids are highlighted for quick duplicate correction. An unreadable
portrait, unmatched capture, missing page, or incomplete coverage blocks
confirmation instead of defaulting an unknown card to owned.

Nothing is written automatically. The upload is already bound to the linked
player tag selected before the DM opens. The member sees a compact collected,
missing, and possible-spare summary, then explicitly saves or cancels. If the
scanner cannot resolve a card state, the review asks for that card directly
before enabling Save. Confirmation rechecks
the selected linked profile, Discord ownership, the session's configured-guild
fence, inventory revision, and exact-card trade reservations, then replaces all
60 states in one conditional inventory update. A temporary failure loading a
different linked account does not block the already selected account's draft.
Discord necessarily receives the DM attachments; the bot drops the raw image
bytes after scanning and stores only the private derived draft for up to 20
minutes.

The dashboard leads with the rendered 60-card board. It is the first thing
`/cards` shows, before anything is clicked, because the collection is what a
member came to see. The board was previously buried under **More > Full board**
on the reasoning that a poster is too small to inspect on a phone; measured at
Discord's mobile width the artwork is legible at roughly 64px per tile and only
the per-tile name captions were not, so the captions were removed rather than
the board. Counts, freshness and the action row sit beneath it. First renders
run off the gateway event loop and identical boards use the renderer's bounded
cache.

The board renders unknown states, so a member who has entered nothing sees the
collection greyed out and can read the goal before doing anything. First run is
the same screen rather than a separate branch; only the primary button changes.

Beneath the board are **four menus, one per category**. Each category fits
inside Discord's 25-option limit, which is what makes all sixty cards reachable
in one interaction with no pagination and no hidden category mode. Every option
carries the card's saved state, so the menus double as a text listing of the
collection. Picking one opens the focused card screen.

There is no setup wall in front of any of this. An earlier build required all
four categories to be complete before a single card could be changed, which
locked out precisely the new members who most needed to correct something; that
gate is gone. Completeness still governs matching, and it is still earned only
by a confirmed scan or a full category review, never by editing one card.

**The focused card screen** shows one card's artwork, its category, its saved
state, and three **absolute** controls: **None**, **Have 1**, and **Spare, 2+**.
The control matching the saved state is green, so the state is readable without
parsing a sentence. Absolute set replaced increment/decrement/keep for three
reasons: it is idempotent, so a stale control cannot double-apply; it has no
unreachable transitions, where the old table had no edge from missing straight
to spare; and it is one write primitive with one revision guard rather than
several. The category menu stays mounted below, so correcting several cards in
one category is pick, tap, pick, tap without returning to the board.

**Edit counts** puts one whole category on one screen. Every category fits a
single Discord select - nineteen options at the largest, against a limit of
twenty-five - so there is nothing to paginate. All of the counts render as ONE
text component, the card menu is a second, and a single `-1 / Set number / +1`
controller acts on whichever card is chosen. The selected card is bold in the
list and named again above the controller.

The list is markdown bullets rather than bare newlines. Nineteen plain lines
pack tightly enough that the troop art runs together, and Discord spaces list
items further apart - the only lever short of a blank line between every card,
which would double the height. Two columns were tested and rejected: the
widest cell is 20-24 characters, so two columns need 43-51 per line against
the roughly 32-40 a phone gives, and the only way to align them is a code
block, which disables markdown and would print `<:Barbarian:123>` literally
instead of the art.

Two earlier shapes are worth recording. Six cards per page with their own
-1/+1 pairs meant twelve large buttons filling a phone while thirteen of
nineteen cards stayed hidden. Putting the card name into the ActionRow as a
button got each card onto one row - an ActionRow is the only Components V2
element that lays out horizontally and it accepts nothing but buttons, and a
Section cannot substitute because its accessory is exactly one Button or one
Thumbnail (`SectionBuilderAccessoriesT`) - but it still showed only six cards.
Note that hikari will build a Section with an ActionRow accessory without
complaining and Discord then rejects the message, so that is a local false
positive rather than a way through.

Counts are digits: 0, 1, 2, 3. The one token is `2+`, the scanner's floor,
where a badge proved a spare exists but not how many - printing a flat 2 would
invent a number. Five English phrasings ("Missing", "Have 1", "3 copies . 2 to
trade") were replaced by the digit, which needs no translation.

The screen is a fixed 15-16 of Discord's 40 components regardless of category
size, against 37 for the paged build. `cards_qty` and `cards_qjump`, the paged
controls, survive as aliases so a panel someone still has open answers with
the new screen rather than "This panel is out of date"; the trailing page
number on those older custom_ids is parsed and ignored. Each write changes only that card,
checks that exact card's reservation, and uses the inventory revision as a
compare-and-swap guard. Accepted swaps on other cards do not block it, so one
held card no longer locks the other eighteen in its category.

When a screenshot proves ownership but the reward bar hides the duplicate
badge, duplicate review also uses the individual card screen. The member sees
the actual artwork and answers **Missing - have 0**, **No - have 1**, or
**Yes - spare**; the next possible spare opens automatically. The Missing
choice also corrects a scanner ownership mistake instead of forcing a separate
manual edit. Review can be finished later without losing the saved scan. All
three paths recheck ownership, guild/session scope, revision, and the affected
card's reservation.

There is no **More** panel. It was eight ungrouped grey buttons mixing
navigation with mutation and carrying no information of its own, so it was
dissolved rather than reorganised: every action moved onto the board's two
control rows, and its two link buttons became masked links in the footer text,
which cost zero component nodes. The **Global Card Chat** deep link opens chat
id `P592bad3209a4408a9ba356469caaaa81`; no login, chat data, or account
credential passes through the bot.

## Screen construction rules

These exist because the first build put every control in a button bar at the
bottom of a wall of prose, which read as bland and made every screen look the
same.

- **A row of things is Sections, not a select.** A collapsed select hides its
  contents behind a tap and shows nothing about them. A `Section` takes a
  `Button` accessory, so each row can carry its own action beside its own text.
  The account picker is the reference implementation. Verified building on the
  pinned stack by `test_account_picker_gives_every_account_its_own_row_and_button`.
- **A select is for choosing among many known things**, where 25 options is the
  cap and the label is enough to choose by. The four category menus qualify;
  a list of five accounts does not.
- **Never ship a screen that is a heading, a line of prose and one control.**
  List what the control is about, so the control confirms rather than reveals.
- **Colour carries meaning.** `DANGER` removes, `SUCCESS` confirms or marks the
  current value, `PRIMARY` is the one thing to do next, and there is at most
  one `PRIMARY` per screen. Grey is for everything else.
- **Container accents come from the data**, not from a house colour: a category
  screen uses `CATEGORY_ACCENTS[category]`.
- **Prefer a masked link to a link button.** It reads the same and costs no
  component node.
- **Lists are bullets grouped by category with the troop's own emoji**, never
  comma-joined runs of names, which wrap into a paragraph on a phone.
  `troop_emoji.markup()` returns `""` for an unsynced troop and never raises.

**Update collection** is the single entry point for every change. The
collection screen itself no longer edits anything: the four category menus,
the sort control, Scan screenshots and Edit counts were four competing routes
to one job, and all of them collapsed into this one button. It opens on the
first category that cannot be traded yet, so first-time setup starts where the
work is. Cards default to one copy, so the member only changes the exceptions.

The category menu sits at the top of that screen, which is what let the old
router - four buttons whose only job was to ask which category - be deleted
outright rather than replaced. Scanning sits at the bottom, below the manual
controls: typing is the main path and scanning is the faster alternative, so
putting them side by side made two unlike things compete. Its warning is
stated plainly, with what to do about it: "Some cards may not be detected.
Check your collection after scanning."

Card sorting was removed with the menus it sorted. It only ever ordered those
four dropdowns - never the rendered board, never any trade screen - so once
they were gone it was a control for a UI that no longer existed. `cards_sort`
is aliased to `cards_dashboard` so an open board redraws instead of erroring.

A category is matchable only once it is in `complete_categories`, because
`find_matches` intersects that field across both players. Two things write it:
a confirmed screenshot scan, which completes all four at once, and the
**Ready to trade** button on the quantity editor, which completes one. That
button is the direct replacement for the old two-list model, where a category
earned completeness by having both its missing and duplicate lists submitted.
It is its own write and not a reuse of `apply_category_selection(mode=
"baseline")`, which resets every card in the category to one copy and would
therefore discard the counts the member had just entered.
**Everything still accurate** refreshes confirmation without re-entering data.

## Family board, matching, and freshness

Matching also fails closed at the configured `CARDS_GUILD_ID` boundary. Both
inventories must carry that guild id, and each candidate must have a current
clan tag found in the configured family-clan list. A missing or mismatched guild
context, an unavailable clan lookup, or an empty family-clan configuration
produces no candidates instead of widening the search. A component interaction
without the configured guild context can never erase or replace an inventory's
existing family scope.

Every confirmed collection acts as that account's durable family-board
listing: missing cards are its wants and duplicate cards are its available
offers. The listing is not tied to one clan, one search, or one open trade.
Members update the same collection after opening packs or completing trades;
they do not recreate a temporary advertisement each time. Accounts may move
between configured family clans without losing their listing.

Any saved list update records a new confirmation time. Once at least one
category is complete, **Everything still accurate** can refresh that time
explicitly. The dashboard labels the age as:

- **Fresh:** at most 24 hours old;
- **Aging:** more than 24 and at most 48 hours old;
- **Stale:** more than 48 hours old.

The matcher has a final 72-hour cutoff. A collection labeled **Stale** therefore
has a short grace period in which it can still appear, with its confirmation
timestamp shown in the result; after 72 hours it is excluded. Incomplete
categories never participate even if another category update made the overall
confirmation time recent.

## Who has what

**Who has what** is a family-wide view reached from the board in one click. For
every card the member is missing it reports how many family collections hold a
spare and how many others still need it, then the reverse for the member's own
spares, then the cards nobody can currently supply.

`family_supply` in `utils/cards.py` is a pure projection of the same documents
the matcher already loads, so the view costs no extra query. Only reviewed
categories count on either side. An untouched category means the member has
told us nothing, and counting it as demand would invent a want out of missing
data.

The panel reports **how many swaps could actually complete at once**, not how
many are listed. A raw count overstates what the family can do, because
completing a swap spends a spare: one member offering a single extra Barbarian
to three partners is one trade, not three. `max_achievable_trades` solves that
resource-constrained matching with a most-constrained-first greedy. The exact
algorithm is a blossom-style search, which is disproportionate machinery for a
hint line, so the greedy is checked against brute force on small inputs
including its known worst case of half the true maximum. The gap is measured
rather than assumed away.

## Family board, matching, and freshness

The broad matcher searches every configured family clan and returns anyone with
a fresh-enough duplicate of a card the requester is missing. It ranks:

1. same current clan;
2. a reciprocal same-category swap;
3. freshest confirmation;
4. stable player name/tag order.

Direct helpers remain visible when they need nothing in return. A reciprocal
option is listed only inside the offered card's category because event trades
cannot cross Elixir, Dark Elixir, Builder Base, and Super Troop sections.
Specific-card results use a paginated two-step picker: first choose a family
holder, then choose a compatible duplicate to give that holder. Pages contain
at most 20 holders, keeping every visible option selectable without silently
truncating Discord's menu limit. Holders in another configured family clan
remain valid proposal targets; moving clans is coordinated only after both
players agree.

## Managed trade lifecycle

From a specific-card result, a member can send a reciprocal proposal to any
eligible account in the configured clan family. The bot rechecks both saved
collections and both public player profiles before creating it, then rechecks
the profiles again at acceptance and before completion. A proposal records
the requested card, the proposed card to give, and the other compatible
duplicates the requester has that the holder needs.

The proposal is posted to the configured `CARDS_CHANNEL_ID` trade board as a
standing post with live **Accept**/**Decline**/**Cancel** buttons, pinging the
holder. The board is the same channel the `/cards` sticky notice lives in: the
notice already pulls eyes there, so the explainer and the trades it explains
are one place rather than two. The post carries a compact visual strip with
the wanted card, offered card, and up to three other compatible offers; the
full text remains the accessible fallback. The Accept button is labeled with
the holder's name and the footer says who may act, because a public button
invites wrong-person taps — the handler refuses anyone but the holder
regardless, but the label is what prevents the attempts. Acceptance posts a
short reply under the standing post that pings the requester. Every other
status change — declined, cancelled, ready, card arrived, completed, expired —
silently edits the standing post in place; an edit cannot notify anyone, and
the transport makes that structural rather than a convention each caller must
remember. DMs remain for the genuinely private notices (the still-trading
check-in, needs-review, auto-deduct), and during the live verification window
the two pinging events also DM; the planned end state is DM only as a
fallback when the channel post fails, which is a one-entry policy change. A
blocked DM or channel-delivery failure never changes the saved proposal or
grants access outside the configured guild and family-clan scope.

An account may have multiple open proposals, up to 25 at once. Each pending or
currently accepting proposal atomically occupies one of 25 lightweight slots
for both accounts; a partial two-account acquisition rolls back by exact trade
id. Temporary slots expire if creation crashes, saved proposals promote their
slots to durable records, and terminal-owner slots are reclaimed on conflict.
Accepted agreements are listed ahead of every unreserved proposal, so proposal
bursts cannot hide move, cancel, or complete controls. Creating a proposal
reserves no cards, does not lock either collection, and does not prevent either
player from considering other matches. There is no 30-minute acceptance
deadline. Declining or cancelling closes only that proposal.

Acceptance revalidates both inventories and confirms that both accounts are
still in configured family clans. Only then does the bot reserve the exact card
states used by the accepted exchange. It does not reserve either whole account,
so the same account may participate in other accepted trades that use different
cards. A particular duplicate cannot be committed to two accepted trades at
once. Accepted agreements do not have the former one-hour member completion
window.

When the accounts are in different family clans, acceptance moves the agreement
to **move needed**. The bot shows both current clans and tells the players to
coordinate a temporary move inside the family; it never kicks, invites, or
moves an account. After they are in the same configured family clan, either
participant can use **Check clans** to mark the agreement **ready in game**.
Only a ready agreement can proceed to in-game execution and completion.

The players still perform both card requests inside Clash of Clans; the bot
does not automate the game client. Immediately before completion, it rechecks
that both accounts remain in the same configured family clan. After both
in-game sides finish, either participant can choose **Trade completed**. A
single conditional state transition owns completion, preventing concurrent
clicks from applying twice. The bot then reloads both inventory documents and
prevalidates the accepted card states and exact-card reservations before writing
either one.

The two inventory documents are updated sequentially; this is not a MongoDB
multi-document transaction and does not promise an atomic both-or-neither
result. When both conditional writes succeed, missing becomes owned and
duplicate becomes owned once for both accounts. A member who still has another
spare marks it again in that category. If prevalidation fails, neither update is
attempted. If a race or storage failure allows zero or only one update to be
confirmed, the bot records the per-account result and leaves the trade as
visible **needs review** in **My trades** for seven days. Before releasing the
exact-card reservation, it marks the affected category incomplete for both
accounts, so uncertain inventory cannot be matched again. Members must inspect
and correct both affected category lists manually; the bot does not guess or
silently roll back a confirmed one-sided update.

Reservation records are separate from completed trade audit rows. **My trades**
provides accept, decline, cancel, check-clan, complete, and refresh actions
without adding another slash command. The standing post is refreshed on every
state change where delivery is available; terminal states collapse it to a
compact closed line rather than deleting it, so the channel keeps a readable
record of what happened. Decline, cancellation, completion, and expiry send no
DM — the edited post is the notification, and it names both players. An
unanswered proposal that expires also closes its post this way; it previously
stayed open-looking in the channel forever. Review-required outcomes keep
their best-effort DM, because a public nag is worse than a private one. A
blocked or failed notification never changes the saved trade outcome. Active
and review-required agreements remain in **My trades**; terminal rows leave
that compact panel while their audit records and the resulting collection state
remain stored.

## Open requests

When the matcher finds nobody holding a wanted card, a member can post an open
request — a public want-ad on the trade board — instead of waiting for a
holder to appear. The event's own rule shapes it: a request cannot be posted
without a same-category duplicate to give back, because the in-game trade has
to start from the other side. A member with no spare is routed to the gem ask
below instead; one **Post a request** button serves both lanes, branching on
whether a spare exists, so the member never has to know which lane they are
in.

An open request pings nobody. By construction it exists because the matcher
found no eligible holder, so there is nobody to aim a ping at; the sticky
notice drives eyes to the channel instead. Each account may hold at most
three open requests at once — a want-ad reserves no cards, but it costs a
public post, so it is bounded tighter than the 25-slot proposal machinery —
and only one per card. A request expires after 48 hours, silently: the post
collapses to its compact closed form and nobody is DMed, because a want-ad
that sat 48 quiet hours is news to no one. The poster can close their own
request from **My trades** at any time, and a request past its deadline stops
rendering as open there even before the sweeper has closed it.

Anyone who can fill the request taps **I have this card**. First tap wins: a
single conditional write moves the request into a short claiming hold, so two
simultaneous claimers always produce exactly one winner and a clear "somebody
got there first" for the other. The claim then converts into an ordinary
managed trade — the poster as requester, the claimer as holder — reusing
every validation, slot, and reservation rule above, and the want-ad's own
message becomes the new trade's standing post, with a short pinging reply for
the poster underneath. If the conversion fails, the claim rolls back and the
want-ad survives untouched. A claim interrupted mid-flight — a crash between
the hold and the conversion — is returned to the board by the deadline
sweeper once its two-minute hold expires, fenced so a newer claim is never
clobbered.

The gem **Ask for help** flow — for the member with no same-category spare to
give back — also lands on the trade board, pinging the one holder being
asked, with the yes/no buttons on the public post. The answer silently
collapses the post and DMs the asker the outcome. Delivery used to be DM-only
and hard-failed: any DM failure deleted the saved ask outright. With the
channel post as the primary surface and the DM demoted to a fallback there is
no single point of delivery left to fail, so that deletion path is gone — a
failed post now leaves a valid saved ask the member can still see in **My
trades**.

## Image scanning boundaries

`utils/card_scan.py` accepts bounded PNG, JPEG, or single-frame WebP stills and
contains no Discord or database access. Its guided batch result deliberately
keeps `PERSISTENCE_SAFE = False`: recognition alone never authorizes a write.
The `/cards` workflow runs it outside the Discord event loop with a bounded
scan semaphore, normalizes its output to a BSON-safe draft, requires all 60
explicit identities and states, and adds the human confirmation plus database
concurrency checks described above.

This is a guided still-image importer, not arbitrary computer vision. Members
must provide two-row collection captures, but their input order does not
matter. Photos, arbitrary crops, video, and layouts whose category colors or
geometry do not match fail closed. Missing sections remain resumable inside the
private session instead of being guessed. The checked-in tests use synthetic
fixtures; the supplied live 1280×591 capture set is a separate manual
calibration oracle and is not retained in the repository. Additional device
and recompression samples should expand that oracle over time without weakening
the unknown-state checks.

Discord's October 2025 File Upload modal component would also accept up to ten
files, but the installed hikari 2.3.5 / lightbulb 3.0.3 stack cannot build or
deserialize the required Label (type 18) and File Upload (type 19) components.
The normal DM composer is therefore the supported one-selection upload surface.
`DM_MESSAGES` is a standard gateway intent and is enabled so the bot receives
only DMs relevant to an existing short-lived session.

Sources checked on 2026-08-10:

- <https://docs.discord.com/developers/components/reference>
- <https://docs.discord.com/developers/events/gateway>
- <https://docs.hikari-py.dev/en/stable/reference/hikari/events/message_events/>
