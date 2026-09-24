# CWL Dashboard

Open this workspace from `/manage` by choosing **CWL**, or select CWL in the
command's optional `section` choice. See [Server Management](manage-dashboard.md).

`/cwl dashboard` opens the current month with no command options. It is the
administrator-only workspace for CWL signup posts,
reminders, and rosters. The CWL button in `/content dashboard` opens the same
workspace. Every interaction rechecks Administrator permission, draft ownership,
and server membership. Manage Server alone does not grant access.

## Three tabs

- **Overview**: signup dates, reminder summary, next post, **Save posts**, and
  pause/resume controls.
- **Messages**: Main Clan and Lazy CWL text, artwork, links, channels, and pings.
- **Schedule**: signup opening, signup closing, and reminder timing.

The red **Skip this message** button asks for confirmation. **Yes, skip** cancels
only the displayed post; **Cancel** returns without changing the schedule.

History, revision restore, and published-post editing controls are removed.
Buttons left on older panels cannot run those actions. Delivery receipts remain
in MongoDB to prevent duplicate posts and restore jobs after a reboot.

## Posts and artwork

Switch between **Main Clan** and **Lazy CWL**, then choose a post. Each post
appears once with a plain description; unused automatic reminder slots are hidden.
Edit text, upload artwork, change
buttons, and select the channel and ping roles. Preview never pings players.
**Save posts** on Overview saves directly and is disabled when nothing has changed.
There is no month-selection or extra review step. **Send roster** queues
the saved roster post; only administrators can use it.

**Upload replacement** uses Discord's native upload modal and the bot's media
store. PNG, JPG, GIF, and WEBP files up to 10 MB are supported. **Post image**
shows the selected artwork. **Restore default image** restores the original.

## Timing

Set **Signups open**, **Signups close**, then **Reminders**. Valid timing forms
save all current edits, including message changes, and immediately update the
sending queue. No extra Start button is needed. Invalid edits show
**NOT SCHEDULED** and preserve the previous active schedule.

Monthly dates require a day of the month or a number of days before month end.
Zero means the final day. Dates 29–31 use the last day in shorter months.
Enter times in the displayed timezone; Discord timestamps use the viewer's
local timezone.

Reminders run from the configured signup opening to closing. Choose an evenly
spaced count or an hourly gap, then set the final reminder's lead time and
minimum spacing. Moving signup dates recalculates unsent reminders. A newly
chosen signup time must be in the future; an existing past opening can still
anchor future reminders without repeating the signup post.

The saved setup **repeats monthly until changed**. Saving updates unsent posts
and carries the same text, artwork, destinations, and timing into later months.
Previously sent posts are not resent. Dated rules repeat on the corresponding
day and time in later months. **Discard changes** reloads saved settings.
Drafts, active settings, and pending jobs survive restarts in MongoDB. Revision
checks prevent an older editor from overwriting a newer save. Submenus provide
Back buttons; old History links return to Overview.
