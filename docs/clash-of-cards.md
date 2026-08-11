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

The bot stores only three states:

- `0`: missing;
- `1`: owned once;
- `2`: two or more copies (at least one tradable duplicate).

This loss of exact duplicate count is deliberate. Discovery needs to know only
whether one spare exists, while asking for every quantity makes 500-player
onboarding much slower. After a trade, a member can revisit the category and
leave the card selected as a duplicate when another spare remains.

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
fails closed instead of shifting card identities. Missing portraits are
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

The normal dashboard is deliberately compact: collection counts, freshness,
one primary action, and only the actions that matter now. The 60-card composite
is available under **More > Full board**, but it is not the main interface.
This avoids presenting phone users with a poster that is too small to inspect.
First board renders still run off the gateway event loop and identical boards
use the renderer's bounded cache.

**Edit cards** opens a game-inspired category browser. Four compact category
chips show collected/total and a check when complete. Selecting Elixir, Dark
Elixir, Builder Base, or Super Troop shows only that category, four individual
cards per mobile-friendly page. Every card has framed artwork, its saved state,
and direct **-1**/**+1** controls. Missing art is gray with an X, spares carry
`x2+`, and possible spares carry `?`. Previous, Find card, and Next avoid the
old category-list workflow. Each write changes only that card, checks its exact
reservation, and uses the inventory revision as a compare-and-swap guard.
Accepted swaps on other cards do not block it; stale controls never overwrite
newer collection data.

When a screenshot proves ownership but the reward bar hides the duplicate
badge, duplicate review also uses the individual card screen. The member sees
the actual artwork and answers **Missing - have 0**, **No - have 1**, or
**Yes - spare**; the next possible spare opens automatically. The Missing
choice also corrects a scanner ownership mistake instead of forcing a separate
manual edit. Review can be finished later without losing the saved scan. All
three paths recheck ownership, guild/session scope, revision, and the affected
card's reservation.

**More** contains the supplied in-game **Global Card Chat** deep link beside
Open in game. It opens chat id `P592bad3209a4408a9ba356469caaaa81`; no login,
chat data, or account credential passes through the bot.

The category editor remains under **Advanced manual editor** for first-time
manual setup or a deliberate full-category rebuild. Every unselected card in a
category defaults to one copy, so the member records only missing/duplicate
exceptions. A category becomes matchable only after both lists have been
reviewed. Category writes retain their bounded revision compare-and-swap retry.
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

The proposal is published to the configured `CARDS_CHANNEL_ID` trade-board
channel and sent to the holder by best-effort DM. Both initial deliveries carry
a compact visual strip with the wanted card, offered card, and up to three
other compatible offers; the full text remains the accessible fallback. A
typical alert is: “Shaun
needs your duplicate Root Rider. Shaun has Wizard and Dragon duplicates that
you need. You are currently in different family clans.” The alert directs both
players to **My trades** for the durable status and actions. Every follow-up DM
includes both player names and tags so a multi-account owner knows which
collection needs attention. A blocked DM or channel-delivery failure never
changes the saved proposal or grants access outside the configured guild and
family-clan scope.

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
without adding another slash command. The trade-board post and participant DMs
are updated on important state changes where delivery is available. Decline,
cancellation, successful completion, and review-required outcomes each make a
best-effort terminal notification to the other participant where applicable. A
blocked or failed notification never changes the saved trade outcome. Active
and review-required agreements remain in **My trades**; terminal rows leave
that compact panel while their audit records and the resulting collection state
remain stored.

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
