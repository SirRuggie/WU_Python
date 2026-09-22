# Recruit setup and content dashboard: decision and evidence

Research date: 2026-09-22. Scope: the three `/setup recruit-*` public
onboarding posts, `/content dashboard`, and replacing their images in R2.
This is a code and documentation review; it does not establish the current
production bucket contents or Discord server configuration.

## Decision

Keep the native Discord Components V2 dashboard and rebuild its missing media
editing path around the existing content renderer and R2 uploader. A separate
website is unnecessary for three documents and would introduce authentication,
hosting, and another preview implementation to maintain. Consider a website
later if bulk asset search, crop tools, or multi-editor approvals become real
requirements.

Use named image slots, upload into an administrator-owned draft, preview the
actual Components V2 output, and explicitly save the template or update a
selected existing post. Store new image bytes under a new content-addressed R2
key. Retain previous objects because existing messages can still reference them.
Replacing an image means changing the document's reference, not overwriting a
shared bucket object.

## Evidence from the starting code

| Finding | Evidence | Consequence |
| --- | --- | --- |
| Text-only editing | `extensions/commands/content.py`: `render`, `_save`, and `panel` only expose/persist `sections` | An administrator cannot replace the galleries through this dashboard. |
| Existing safeguards are reusable | Same module: `require_editor`, `new_draft`, `_save`, `publish` | Preserve per-user/guild ownership, draft expiry, revision checks, and publication leases. |
| Linked media is not adopted | `ContentDashboard.invoke` captures text and component shape; `publish` compares text | An image-only external edit can be missed, and rendering can restore baseline art. |
| Tight Family Particulars budget | `tests/test_content_dashboard.py::test_native_document_baselines_keep_original_layout_and_text_totals` | The starting layout has 40 components and 3,992 text characters. Keep image controls outside the public document preview. |
| Setup lacks an invocation permission check | The three `extensions/commands/setup/recruit_*.py` `invoke` methods | Apply the same Manage Server rule as the editor before public posting. |
| Onboarding dependencies are hardcoded | Each setup module's acknowledgement role and next-channel constants | Check that they exist in the current guild and that the bot can assign the role before posting. |
| R2 already uses immutable version URLs | `utils/media_store.py`: `object_key`, `upload_bytes_blocking`, `CACHE_CONTROL` | Reuse this implementation and namespace replacement uploads by guild/document. |
| Native upload modal models are unavailable in the installed SDK | `.venv/bin/python`: Hikari reports `2.6.0`; `hikari.impl` exposes no names containing `Upload` or `Label` | Use a narrow raw-component/deserialization adapter for Discord's types 18 and 19; retain the slash-command attachment as a fallback without forcing an unrelated framework upgrade. |

## Primary-source research

1. [Discord component reference](https://docs.discord.com/developers/components/reference):
   Components V2 messages allow 40 total components and use Text Display,
   Containers, and Media Galleries. File Upload is a modal component nested
   inside a Label. Discord API support does not imply support in the installed
   Python library.
2. [Discord application commands](https://docs.discord.com/developers/interactions/application-commands):
   attachment options are supported by slash commands, providing an upload
   route compatible with the current bot framework.
3. [Cloudflare R2 consistency](https://developers.cloudflare.com/r2/reference/consistency/):
   R2 writes are strongly consistent, but overwriting an object behind a cached
   custom domain can continue serving its old bytes until cache expiration or
   purge. This supports using new URLs for replacement images.
4. [Cloudflare R2 caching](https://developers.cloudflare.com/cache/interaction-cloudflare-products/r2/):
   cached delivery uses a custom domain; the development `r2.dev` endpoint
   does not offer those cache features.
5. [Discord permissions](https://docs.discord.com/developers/topics/permissions):
   role assignment requires the bot's role to be higher than the assigned
   role. Administrator permission does not remove the role hierarchy rule.
6. [Discord signed attachment URLs](https://docs.discord.com/developers/reference#signed-attachment-cdn-urls):
   attachment signatures expire and refresh when messages are fetched. Compare
   stable attachment identity rather than treating refreshed signature query
   parameters as an image edit. Discord documents accepting parameter-free CDN
   references in API URL fields.

The renderer's 4,000-character total is the existing application policy. The
current component reference explicitly documents a 4,000-character Text Input
limit; avoid representing that field limit alone as proof of a total-message
limit. This change preserves the established application budget.

## Scope and follow-on design

This pass addresses editable images, safe adoption/publication, and setup
readiness. A full onboarding state-machine rewrite is a different change:
it would need a migration of acknowledgement roles, existing messages,
channel overwrites, and cleanup jobs. Keep the current roles and channels
until those dependencies have an explicit migration design.

Luna's scout also found existing permission issues in the separate recruiter,
clan upload, and FWA upload dashboards, already recorded as AUTH-001/002/003 in
`docs/backlog.md`. These are separate surfaces from the three setup posts and
content editor. This pass does not claim to resolve those backlog entries.

For a later editor expansion, replace positional text arrays with versioned
semantic block IDs, introduce revision history and restore, and persist the
canonical message ID for each document so an administrator does not need to
paste its link. A canonical-post registry must include deliberate replacement
and deleted-message recovery to avoid duplicate public onboarding posts.

## Release verification

Completed locally:

- Sol's final independent review found no blocking issue. The content,
  MediaStore, and recruit-setup suite passed **86 repository tests**, plus
  **2 temporary adversarial tests** (88 total in that run). Those attacks
  checked rejected uploads before any attachment read/R2 write and a reset
  followed by two successful updates despite refreshed Discord signatures.
- A real Hikari 2.6 request-payload regression checks that an unchanged Discord
  attachment is retained while a replaced attachment is omitted and a bundled
  reset image is uploaded. This prevents both image loss and duplicate growth.
- Sol independently ran 121 tests across setup checks, MediaStore, static
  uploads, R2 migration, media URLs, image fetching/validation, and FWA images:
  all passed. These use test doubles, not production Discord or R2 writes.
  This related suite overlaps the final suite; the counts are not additive.
- The orchestrator ran `check_static_bytes` against all 95 supported image
  files under `assets/`: zero failures with the stricter decoder validation.
- A sandbox-only executor-shutdown hang was reproduced with
  `asyncio.run(asyncio.to_thread(lambda: 1))`. The same diagnostic passed
  outside the sandbox; the independent test run used that working environment.

Covered behaviors include ownership and permission rejection, native builder and
REST-model media handling, cache-safe replacement keys, template revision
conflicts, image-only publication conflicts, reset/preview, and setup readiness.
Live acceptance remains separate: deploy normally, run the setup check, upload
a small test image into a draft, preview it, and update a chosen test post.
Confirm acknowledgement buttons still work and future setup posts use the saved
image. Do not start another production gateway process locally to perform this
check.
