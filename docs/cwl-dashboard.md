# CWL Campaign Dashboard

`/cwl dashboard` is the private administrator workspace for every CWL message.
It replaces the need to edit individual reminder commands when changing a
message, its Main/Lazy copy, artwork, button links, timing, destination, or
role ping.

The dashboard opens a durable draft for the selected CWL cycle. Reopening it
resumes that administrator's saved draft rather than starting over. Closing
Discord does not discard edits. Every button rechecks that the clicker has
Manage Server or Administrator permission, owns that draft, and is still in the
originating guild.

## Workflow

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

Open **Schedule** to set a message to run monthly, after signups open, before
the signup deadline, at one specific date and time, manually, or using a legacy
reminder chain. The panel shows the next resolved occurrences in the configured
timezone. **Settings** holds the single campaign signup deadline and timezone;
deadline-aware reminders follow that one value.

Use **Preview** from a message version to render the same Components V2 message
the scheduler will use. Previews suppress every user, role, and everyone ping.
They never send a post or alter delivery history.

When the draft is ready, select **Review this month** or **Review monthly
defaults**. The review shows the exact changed messages, artwork, links,
audiences, schedule dates, and deadline before presenting the final apply
button. Confirmation reloads the draft and refuses to apply if it changed after
review. Applying uses a revision check so an older editor cannot silently
overwrite a newer saved campaign. This-month applies protect already-sent posts.
If an apply reports that another administrator saved first, use **Reload saved
version** in Settings. It asks for a second confirmation, discards only your
owned draft, and opens a fresh draft from the current saved campaign. It never
automatically rebases or merges conflicting edits.

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
