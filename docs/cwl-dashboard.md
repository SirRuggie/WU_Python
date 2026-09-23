# CWL Campaign Dashboard

`/cwl dashboard` is the private administrator workspace for every CWL message.
It replaces the need to edit individual reminder commands when changing a
message, its Main/Lazy copy, artwork, button links, timing, destination, or
role ping.

The dashboard opens a durable draft for the selected CWL cycle. With no month
selected, it opens the current month, never an older month's draft. Reopening it
resumes that administrator's saved draft for that month rather than starting over.
Closing Discord does not discard edits. A successful timing change keeps the
same draft open and refreshes it to the saved revision, so the next form can use
the same dashboard session. Every button rechecks that the clicker has
Manage Server or Administrator permission, owns that draft, and is still in the
originating guild.

## Workflow

The main navigation has four tabs: **Overview**, **Messages**, **Schedule**, and
**History**. Schedule includes all timing settings; old Settings links redirect
there. Submenus omit the main tabs and provide an enabled Back button naming
the destination. The main tabs remain clickable, including the selected tab.

Open **Messages**, choose an announcement and its **Main** or **Lazy** version,
then use the focused controls to rename the dashboard item, edit text, upload
an image, update buttons, or change delivery settings. **Copy text** preserves
the other version's links and destination. **Duplicate** creates an independent
reminder with its own dashboard name and schedule. The one-screen message menu
supports up to twelve messages per campaign.

The image control opens Discord's native file-upload modal and saves the
attachment to the bot's media store. It accepts PNG, JPG, GIF, and WEBP files
up to 10 MB. The pinned Discord SDK cannot yet decode file-upload modal
components, so a narrowly scoped gateway bridge accepts only CWL image-upload
payloads and validates the interaction owner, server, attachment type, and
size before uploading.

Each message editor displays **Current image in this draft**. Use **Upload
replacement** to replace it; the preview refreshes as soon as the upload saves
to the draft. **Restore default image** explains that it returns the native
artwork and is disabled when that artwork is already selected.

Open **Schedule** and follow the steps: **Signups open**, **Signups close**, then
**Reminders**. Opening and closing controls are together, and the upcoming list
shows only future draft messages. Advanced controls retain other message timing
options. The configured timezone is shown beside the dates; Discord date labels
render in each viewer's local timezone. Submitting a valid timing form saves it
immediately and updates the durable delivery queue. That save applies the whole
current draft atomically, including any text, artwork, buttons, destinations,
or ping changes already in it. Review those edits before submitting a timing
form. There is no separate Review, Save, or Start button for current timing
changes.

Overview shows signup opening, closing, and reminder settings. Valid timing
forms are already in use. Use **Save message changes** from Overview when those
content or delivery edits should be saved without changing timing. A later valid
timing submission also saves them as part of the complete draft. The panel shows
one **Next message** when the displayed settings match those in use. Both drafts
and active settings are stored in MongoDB and survive bot restarts.

If a timing edit cannot produce a valid plan, the dashboard keeps the edit in
the draft and labels it **NOT SCHEDULED**. The previously active sending plan
and its queued jobs remain unchanged while the dates are corrected. A newly
chosen signup opening in the past is rejected from scheduling in the same way.
An opening that was already active and has since passed remains a valid reminder
anchor; changing its future closing date or reminders does not replay the old
signup post.

### Reminder sequence

Use **Edit reminders** in Schedule to configure numbered sign-up reminders.
Choose **Evenly spread reminders** to set the number of reminders, final-call
lead time, and minimum gap. Choose **Every X hours** to set only the interval,
final-call lead time, and minimum gap; it keeps the existing count internally
because interval timing determines how many slots can fit. The recommended
starting plan is four evenly spread reminders, with the final call three hours
before signup close and a three-hour minimum gap. The panel resolves and shows
signup opening, deadline, final reminder, and **View all send times** before
the form is submitted. A valid submission saves the sequence and updates its
queued delivery jobs immediately. The reminder count includes the final
reminder. If a new opening or closing date temporarily makes the plan
impossible, the date edit still saves to the draft with a **NOT SCHEDULED**
warning. Complete the other date edit to make the plan valid; the previous live
plan stays in place until then.

Reminders always calculate from the configured signup opening and closing
dates. A delivered signup post does not freeze the opening date: an explicit
date edit moves the remaining reminders while preserving delivered content and
preventing duplicate sends. Old compatibility schedule fields cannot silently
override an explicitly edited date.

Configuring a sequence preserves the text and artwork of numbered reminder
slots. It activates only the slots that have a resolved send time; unused slots
are explicitly marked in Messages. Main and Lazy versions share each slot's
time. While a sequence is active, individual numbered schedule controls lead
back to the sequence editor so there is no hidden, ignored timing. Existing
legacy individual reminder timing remains unchanged until an administrator
explicitly configures a sequence.

Choosing **Monthly** requires a choice of **Day of the month** (1–31) or
**Days before month end** (0–27), followed by a required number and delivery
time. Zero means the month's last day; two means two days before that day.
Dates 29–31 use the last day in shorter months. Existing schedules are kept
when the submitted rule is invalid. A valid rule saves and replaces the active
timing immediately.

Use **Preview** from a message version to render the same Components V2 message
the scheduler will use. Previews suppress every user, role, and everyone ping.
They never send a post or alter delivery history.

When message content or delivery settings are ready, select **Save message
changes** on Overview, choose the displayed month or **Future months**, then
review the exact changed text, artwork, links, audiences, and destinations
before the final save. Confirmation reloads the draft and refuses to save if it
changed after review. Saving uses a revision check so an older editor cannot
silently overwrite a newer campaign. This-month saves protect already-sent
posts.

To reuse the current draft's settings in later cycles, open **Schedule → More
options → Repeat for future months** and review the first affected future month.
Saving future-month defaults leaves the current month's active campaign
unchanged.
If a save reports that another administrator saved first, use **Schedule → More
options → Discard changes… → Discard and reload**. It asks for a second
confirmation, discards only your owned draft, and opens a fresh draft from the
current saved campaign. It never automatically rebases or merges conflicting
edits.

The overview can pause/resume the campaign and skip the next scheduled
occurrence. **History** records sends, skips, failures, revision restores, and
links to published posts. A failed occurrence can be queued for retry. Updating
a published post first fingerprints it, then asks for a final confirmation; it
rechecks the message and draft before editing with pings suppressed. Those
actions are handled by the delivery service, so editing and previewing never
send a production message.

## Acceptance checks

- Open `/cwl dashboard` twice as the same administrator and verify the second
  panel resumes the prior draft.
- Edit Main and Lazy copy, artwork, links, channel, roles, schedule, and
  deadline; preview both audiences and confirm previews contain no role pings.
- Submit valid opening, closing, and reminder forms and verify the dashboard
  immediately shows **Scheduled** without a second save step. Submit an invalid
  combination and verify **NOT SCHEDULED** appears while the previous queue is
  unchanged.
- Review both scope choices and verify the summary matches the selected target.
  Edit the draft after review and verify confirmation refuses it.
- Verify history links, retry, revision restore, and published-post update use
  the expected owned CWL occurrence.

Automated coverage exercises the dashboard, campaign persistence, upload bridge,
and publishing preparation. It does not perform live Discord sends or deploy
configuration changes.

## Content dashboard entry point

The **CWL announcements** button in `/content dashboard` opens the same private
CWL draft editor. It is intended as the main entry point for administrators who
already use the content dashboard for published posts.

`/cwl dashboard` and that content-dashboard button are the only announcement
editing entry points. Main and Lazy messages, signup posts, reminder sequences,
and roster announcements are all configured and delivered from this dashboard.
