# `/profile` and the New Warrior alert

`/profile` shows one Discord user and every Clash account linked to them. The
same card is the staff "New Warrior" alert posted when someone joins Warriors
United. Both replaced `/accounts` and `/user-accounts` (removed 2026-11-10,
Ruggie's decision in the "Add staff alert for new joiners" thread).

Code: `extensions/commands/profile.py` (command, card, buttons),
`extensions/events/new_warrior_alert.py` (join listener),
`extensions/commands/linked_accounts.py` (shared loader and rows; no command).

## Command

`/profile [discord_user]`. The option uses Discord's native user picker. Empty
means the user who ran it. Any member can use it. The reply is public and never
pings anyone (`user_mentions`, `role_mentions`, `mentions_everyone` all off).

## Card (Components V2)

Brand gold accent (`WU_GOLD`) and `assets/Gold_Footer.png`, on both `/profile` and
the alert (Ruggie, 2026-11-10).

1. Identity: the display name as plain text, then the username as a link to
   `discord.com/users/<id>` ("Discord profile" when the username is not a
   plain a-z/0-9/_/. name). Names stay out of link labels because Discord
   drops a masked link when its label holds some characters (seen live with
   "❤️MC QUEEN❤️"). "Account created", and "Joined server" for members. The
   avatar is the thumbnail (guild avatar first). No mention: Discord renders
   unknown mentions as "Unknown user". No raw Discord ID is shown as text.
2. Separator.
3. `## Linked Accounts`, a summary, and one row per linked tag: Town Hall,
   player name (bold, plain), the tag linked to the in-game profile, clan. Sorted by Town Hall.
   20 rows per page.
4. Notes: incomplete list (a provider did not answer), profiles not loaded,
   tags with no player profile, Clash maintenance.
5. Buttons: ◀ Page n/N ▶ (only with more than one page) and Refresh.

Empty states:

- No links: `No linked accounts` and `Not linked in ClashKing or ClashPerk.`
  The identity part still shows.
- A provider is down: the incomplete-list note names it. An outage is never
  shown as "No linked accounts".

## Links

Forward links from ClashKing and ClashPerk are merged
(`utils.recruit_links.resolve(discord_id, verify_owners=False)`), with each tag
once. These are links, not verified ownership: about 99% are unverified, and
none are required to be verified. Reverse ownership disputes do not remove tags.

Every linked tag gets exactly one row:

```text
linked tags = loaded profiles + profile-not-found tags + temporary failures
```

`coc.NotFound` keeps the tag as `Player profile not found`. A transient failure
keeps the tag as `Account not loaded` with a retry note.

## Buttons and cache

Custom IDs: `profile_page:<user_id>:<page>:<mode>` and
`profile_refresh:<user_id>:<page>:<mode>`; mode `p` is `/profile`, `a` is the
alert (keeps the alert title). Buttons carry the target only; any viewer can
page, and the card never switches to the clicker. Out-of-range pages clamp.
Old `/user-accounts` buttons (`user_accounts_page:<id>:<page>`) are an alias of
`profile_page`; old `/accounts` buttons get the stale-panel message.

A 2-minute merged-result cache keeps paging stable. The command and Refresh
bypass it. `/manage-links` clears it for the affected users
(`linked_accounts.forget`).

## New Warrior alert

- Trigger: `MemberCreateEvent` in guild 644963518025826315. Bots are skipped.
  Every join, including a rejoin, posts once.
- Channel: 967257753804505108 (staff only; `NEW_WARRIOR_ALERT_CHANNEL_ID`).
- Card: `# ⛩️ New Warrior at the Gate` (the ⛩️ of the Knocking on the Gate role), a ping of role 1151305219079155802, then the
  profile card. Only that role can be pinged (`role_mentions=[role]`); the new
  member and @everyone are never pinged. Page and Refresh edits do not ping
  again.
- Most new members link after they join, so the alert often shows "No linked
  accounts". Staff select Refresh to reload. There is no polling.
- A link lookup failure still posts the alert with the incomplete note. A send
  failure is logged and never retried, because Discord may already have
  accepted it. The join log and profile listeners are separate and unaffected.
