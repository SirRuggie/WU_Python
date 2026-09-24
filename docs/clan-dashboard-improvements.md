# Clan dashboard image review — 2026-09-23

Compared `/clan dashboard` with `/cwl dashboard` and `/content dashboard`.
This review covers code and serialized Discord payloads, not measured live
Discord client latency.

## Existing image delivery

CWL/content uploads validate image bytes, store content-addressed R2 objects,
and update the selected draft preview. Changing bytes changes the URL, avoiding
stale cached artwork. Native file-upload modals require compatibility adapters
because the pinned Hikari 2.6.0 does not decode these fields itself.

Clan logos already use `optimized(..., width=THUMBNAIL)` (256 pixels). FWA maps
use DETAIL (1600 pixels), appropriate for inspecting base layouts. R2 resizing
only happens when Cloudflare transformations and `R2_IMAGE_TRANSFORMS` are
enabled; otherwise original URLs are used. This review did not change hosting
configuration or verify the live Cloudflare account.

Hikari 2.6.0 already fixes the older URL download/re-upload behavior. There is
no need to upgrade dependencies to obtain that fix.

## Implemented

- Replaced 27 local decorative footer galleries throughout clan administration
  with native separators. The colored container accents remain. These screens
  no longer require an attachment upload just to draw their footer.
- Requested the root server icon at 256 pixels instead of the SDK default of
  4096, and handled iconless servers and guild-cache misses with a text heading.
- Counted clans in Mongo instead of retrieving and constructing every clan
  record just to display the total.
- Added native upload dialogs for clan logos/banners and FWA war/active bases,
  with image-only file filters and same-message previews.

## Upload an image

Open `/clan dashboard`, choose a clan under **Update Clan Information**, then
**Manage Images**. The panel previews the current logo and banner; choose
**Upload Logo** or **Upload Banner**, attach one image and submit.

For FWA, choose **Manage FWA Data**, select a Town Hall, open its image controls,
and choose **Upload War Base** or **Upload Active Base**.

Submitting saves the selected replacement immediately, matching the existing
clan editor's save behavior. The refreshed panel shows the saved image and
provides another upload button and a return to the editor. There is no separate
Save step. PNG, JPG, GIF and WEBP are supported up to the bot's 10 MB limit.
The existing URL controls remain available. The legacy `/clan upload-images`
and `/fwa upload-images` commands have been removed; old instruction buttons
redirect to these dashboard controls. Discord receives the command removals
on the next bot startup and command sync.

Each modal is bound to the user, server, source message/channel, image slot and
clan/Town Hall that opened it. Submissions recheck the management role. Upload
sessions are short-lived and are lost on restart; reopen the upload if it has
expired. Concurrent changes to the same saved image are rejected rather than
silently overwritten. Independent logo/banner or war/active slots can change
separately.

Uploads use validated, content-addressed R2 objects. Only the selected database
field changes; FWA delivery maps refresh after persistence succeeds. Previous
objects remain available for old posts. Failed or stale uploads may leave an
unreferenced object; automatic object cleanup is outside this change.

## Newer components used and deferred

Native File Upload modals and image file-type filters are now used here.
Discord added file-type filters on August 5, 2026. Byte validation still runs
on the server; a filename filter does not prove a file is a valid image.
Modal selects, radio groups and checkboxes remain optional future form work:
they do not improve image delivery and need additional SDK compatibility work.

Discord increased its default upload limit to 20 MiB on September 3, 2026.
That does not change the bot's deliberately separate 10 MB image validation
limit. Raising it is unnecessary for dashboard thumbnails.

Sources: [Discord changelog](https://docs.discord.com/developers/change-log),
[component reference](https://docs.discord.com/developers/components/reference),
[Hikari releases](https://github.com/hikari-py/hikari/releases/tag/2.6.0).
