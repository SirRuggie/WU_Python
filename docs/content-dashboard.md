# Content dashboard

The shared management home is `/manage`; choose **Recruit Gauntlet** for this
onboarding editor, or use the optional `section` choice to open it directly.
See [Server Management](manage-dashboard.md) for navigation and permissions.

Recruit Gauntlet is a private, per-server Components V2 editor for About Us,
WU Strike System, and Family Particulars. Administrators with Manage Server can
edit named Markdown blocks, replace images in R2, preview the public layout,
save a reusable template, and send the current draft to a selected channel.

Manage CWL messages, artwork, destinations, and timing through **CWL** in
`/manage` (or its optional `section` choice); see [CWL dashboard](cwl-dashboard.md).

## Choose a channel and send

Each document (About Us, WU Strike System, and Family Particulars) has its own
native Discord channel dropdown and **Send to channel** button. Choose a text
or announcement channel in this server. The choice is saved per server and
document and is shown in the editor when reopened. MongoDB stores it separately
from template text under `content_destination:<server id>:<document>` in
`bot_config`.

**Send to channel** publishes the current draft, including its text and artwork.
**Save template** separately saves those edits as the starting point for future
editing. Sending does not overwrite earlier posts or save the draft as a template.
After a successful send, the editor provides a link to the new post.

The acknowledgement buttons and their role grants remain attached to the posted
messages. The selected destination controls where this document is posted; it
does not change the existing acknowledgement roles or next-step channel links.
Bot access to the destination and acknowledgement setup are checked before sending.

The dashboard replaces `/setup recruit-aboutus`, `/setup recruit-strikesystem`,
and `/setup recruit-familyparticulars`; those three slash commands are retired.
`/setup recruit-check` remains available for onboarding diagnostics.

## Replace an image

1. Open `/manage` and choose **Recruit Gauntlet**.
2. Choose the document to edit.
3. Select the image in the image menu. The editor shows its current draft image
   beneath the menu so you can confirm the selection, then click **Upload replacement**.
4. Choose a PNG, JPG, GIF, or WEBP in Discord's upload modal. It must fit the
   bot's 10 MB byte and 40-million-pixel limits.
5. The preview refreshes to the uploaded image in the same private editor.
   The image is uploaded to R2 but is still
   a draft; the template and public post have not changed.
6. Use **Preview**, then **Save template** for future setup posts. Saving a
   template does not update previously published messages.

Images are uploaded through the dashboard's **Upload replacement** button;
there is no separate upload command. The uploader must still own the draft,
be in the same guild, and have Manage Server permission.

To restore the original artwork, select the image and click **Restore default
image**, then preview and use the green **Save template** button.
The restore button is disabled when the draft already uses the default image.
The selection stays active and the editor immediately shows the restored default.

| Document | Editable images |
| --- | --- |
| About Us | Welcome banner |
| WU Strike System | Basic rules banner; main clan strike chart; FWA strike chart |
| Family Particulars | Welcome banner; CWL banner |

## Storage and publication

Templates live at `content:<document>:<guild id>` in MongoDB with text sections,
named `media` overrides, a revision, and the most recent editor/time. Missing
media fields retain the bundled defaults, so existing records require no bulk
migration. About Us also reads its previous `recruit_aboutus:<guild id>` record
when no unified template is available.

Uploads use `content/recruit/<guild id>/<document>/<slot>.<hash>.<extension>` in
R2. Changed image bytes produce a new URL. Previous objects remain available
because older posts may still reference them. Abandoned drafts can therefore
leave unused objects; automatic garbage collection and full revision-history
restore are not included. Reset restores the bundled default, not an arbitrary
previous uploaded version.

Drafts expire after 30 minutes and recheck user, guild, and Manage Server on
every interaction. Saving uses revision compare-and-swap. Linked post adoption
checks the bot author, guild, layout, text, and media. Updating a linked post
uses a short lease and rejects changes made since the draft opened. Discord's
rotating attachment signatures are normalized when comparing image identity.
When editing, the bot retains existing Discord attachments still used by the
rendered galleries and replaces unused ones. Legacy artwork adopted from a
Discord attachment still depends on that source attachment; use R2 uploads for
independent, durable image hosting. A saved reference is not a backup of a
Discord attachment that is later deleted or replaced.

Preview uses the public renderer and reuses its acknowledgement button as
**Back to editor**. This keeps Family Particulars within its existing 40-component
layout. Decorative text stays fixed and still counts toward the bot's
4,000-character total policy. Published acknowledgement actions retain their
original role behavior.

## Setup checks

Run `/setup recruit-check` in the intended posting channel for a private
Components V2 report. The three `/setup recruit-*` commands now require Manage
Server and check prerequisites before posting: current-channel permissions,
acknowledgement role existence and assignability, and next-channel guild/type.
The report also indicates whether R2 configuration is present; this is not a
live bucket write test.

The onboarding role/channel IDs remain the current configured constants. The
check does not prove that every recruit's channel overwrites allow the next
step. Validate that with a test member during deployment.

See [research, architecture decision, and evidence](recruit-content-improvements.md)
for the primary sources and remaining design work.

## Native upload compatibility and verification

Discord's [File Upload component](https://docs.discord.com/developers/components/reference#file-upload)
uses a Label (type 18) containing a File Upload (type 19). Submission values
identify entries in `data.resolved.attachments`. The pinned Hikari 2.6.0 does
not expose those modal fields, so `utils/discord_file_upload.py` preserves only
`content_upload_submit:` submissions for one-shot consumption. Its cache is
bounded to 256 entries and expires entries after 20 minutes. `main.py` installs
the adapter before constructing `GatewayBot`, which caches its deserializers.

Verification on 2026-09-22:

- 18 native-upload tests cover documented payload deserialization, startup
  ordering, modal construction, dispatcher routing, same-editor updates,
  permissions/ownership/expiry, invalid files, upload failures, row limits,
  and the existing text-modal path.
- 141 focused upload, dashboard, dispatcher, state, startup, storage, and
  recruit-setup tests passed. Compilation and diff/encoding/structure checks
  passed.
- The full suite produced 2,320 passes, 2 skips, and 3 failures. All three
  failures were reproduced from unchanged baseline commit `1580736`: two
  clan-logo error-response fixtures lack the required role/context shape,
  and the help-catalog test expects 104 paths where the baseline has 105.
- A sandbox-only asyncio stall was isolated: the same card-trading test
  completed outside the sandbox. The full suite above ran outside it.

These tests exercise application/SDK behavior with simulated Discord uploads;
they do not establish a successful upload from a live Discord client.
