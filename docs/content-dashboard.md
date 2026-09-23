# Content dashboard

`/content dashboard` is a private, per-server Components V2 editor for About Us,
WU Strike System, and Family Particulars. Administrators with Manage Server can
edit named Markdown blocks, replace images in R2, preview the public layout,
save a template, and update a selected existing bot post.

The root panel also includes **CWL announcements**, which opens the private
`/cwl dashboard` campaign editor. CWL messages, artwork, destinations, and
timing are managed together there; see [CWL dashboard](cwl-dashboard.md).

## Replace an image

1. Open `/content dashboard`. To update an existing post, supply its Discord
   message link in `message-link`.
2. Choose the document if it was not selected by the message link.
3. Select the image in the image menu. The panel gives you a command containing
   the selected draft ID.
4. Run `/content image-upload draft:<shown ID> image:<attachment>`. Use a PNG,
   JPG, GIF, or WEBP within the bot's 10 MB byte and 40-million-pixel limits.
5. Continue in the **new private editor returned by the upload command**. The
   image is uploaded to R2 but is still a draft; the template and public post
   have not changed.
6. Use **Preview**, then **Save template** for future setup posts and/or
   **Update selected post** for the linked message. These are separate actions;
   saving a template does not update all previously published messages.

The original editor remains an older draft. Continue in the newest one to keep
the uploaded image and any edits together. A draft ID is not authorization:
the uploader must still be its owner, in the same guild, with Manage Server.

To restore the original artwork, select the image and click **Reset selected
image**, then preview and save or update the selected post.

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
