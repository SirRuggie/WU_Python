# CWL Dashboard

Open `/manage` → **CWL**. Administrator permission is required and rechecked on every action. The private editor opens the current month and retains your setup across months and bot restarts.

## Publish Final Roster

Choose **Publish Final Roster** on the opening screen. **Both** is selected initially; Main CWL and Lazy CWL are also available separately. Existing spreadsheet links and saved announcements are reused.

Press **Publish to Both Channels** to send immediately, without a required preview or confirmation. Each audience has optional Edit message, Change link, and Preview controls. Each successful send shows View post. Retry failed announcement sends only failed audiences; successful announcements are not duplicated. Automatic signup reminders can remain paused while publishing a final roster.

## Editing

Messages contains the Main and Lazy templates. Submitted text, link, artwork, channel, and ping-role changes save automatically for future posts. There is no separate Save step. Dismissing a modal cancels its unsubmitted input. Preview never pings members, and saving does not send a message or rewrite an existing announcement.

Artwork supports PNG, JPG, GIF, and WEBP up to 10 MB. Existing Upload replacement, Restore default image, and template customization tools remain available. Saving content does not apply a previously rejected timing edit. Concurrent edits use revision checks.

## Signup Reminders

The screen shows running/paused/problem status, the next send, and the latest delivery result. Choose Main CWL, Lazy CWL, or Both; edit signup opening, closing, and reminder timing. Valid submissions save automatically. Running schedules update upcoming messages; paused schedules remain paused. Use Start Reminders or Pause Reminders separately. New setups do not start simply because a form was submitted.

Choose evenly spaced reminders or an hourly gap. The final reminder is included in the pattern, with an editable lead time before signups close. Minimum spacing remains available. The setup repeats monthly until manually changed and never resets at month rollover. Specific-date inputs also carry forward as monthly rules. Monthly days 29–31 clamp to the last day in shorter months.

Times are entered in the displayed campaign timezone; Discord timestamps display in the viewer's local timezone. Invalid timing retains the previous active schedule and reports the problem. Previously sent messages are not resent. Skip this message retains its confirmation. Failed reminders have a contextual retry action.

## Related tools

**CWL Return Pings** manages saved clan members and return pings, not the published assignment spreadsheet. See [CWL Return Pings](lazycwl-dashboard.md) and the [agreed War Operations decisions](war-operations-ux-review.md).

The retired `/cwl dashboard` and `/cwl rosters` slash-command entry points remain retired. Use `/manage`.
