# Media hosting: the Cloudinary bandwidth incident, and where the images should live

Research, 2026-09-02. Vendor numbers were checked against official
documentation on that date; anything that could not be verified is marked
*unverified*. The hikari behaviour in section 2 was reproduced in a scratch
venv against the exact pinned version and is not in doubt.

> **Status.** Decided the same day: **Cloudflare R2**, because the family's
> domain is already on Cloudflare. Main had already shipped the static art
> into `assets/branding/` and the render-time size cap
> (`utils/cloudinary_urls.optimized`, commit `74efd85`, which also put
> August's usage at 116 GB). The R2 move is built on top of that:
> `utils/media_store.py` uploads, `utils/media_urls.py` builds delivery URLs
> for both hosts while rows migrate, and `tools/migrate_media_to_r2.py`
> moves the Mongo rows. Setup and the runbook are in
> [deployment.md](deployment.md#cloudflare-r2-image-uploads). **Still open:**
> the hikari double-fetch in section 2.2, by shim or by upgrade.

## TL;DR

- 🧨 **Cloudinary was not the cause, only where the bill landed.** Three
  multipliers stacked: full-size originals used as 80 px thumbnails, a hikari
  2.3.5 bug that makes the **bot itself download every image URL on every
  send and every edit**, and `/todo`'s ten-minute self-edit for up to 30 days
  per DM session.
- 🐛 The hikari bug is real, reproduced, and fixed upstream in **hikari 2.6.0
  (2026-08-19)**. It can be closed today with a ten-line startup shim
  (section 3), validated against 2.3.5, or by the coupled upgrade to
  hikari 2.6.0 + hikari-lightbulb 3.2.6.
- 🏆 **Recommended replacement: Cloudflare R2** behind a small `MediaStore`
  wrapper. Free egress, S3 API, 10 GB and 10 million reads a month free, so
  a repeat of this incident cannot produce a bill. Static art moves into the
  repo's `assets/` folder, which the bot already attaches from disk for every
  footer. `/todo` thumbnails become a small generated variant, or the
  Discord-hosted application emoji the dashboard already creates.
- ❌ Not worth it: Imgur, ImgBB, Catbox and friends (terms forbid it or promise
  nothing), Supabase/Appwrite (free projects pause), Firebase (Blaze plan now
  required), Cloudimage/Scaleway/Storj (free tiers withdrawn).
- ✅ After the thumbnail and double-fetch fixes, Cloudinary's free plan would
  survive too. It stays metered, though, so the next leaky feature bills us
  the same way; the point of moving is to make that impossible.

## 1. What the bot hosts

| Class | Count | Written by | Rendered where | Needs |
|---|---|---|---|---|
| **Static art** | 20 fixed URLs, hard-coded in code (`WU_Logo.png`, six `server_banners/*.png`, seven `misc_images` GIF/JPG/PNG, `Default_FWA_Base.jpg`, `TH_Weight.png`, `CW_Leagues.png`, `Denied.png`, `FWA.png`, `WU_FWA_Ticket.jpg`) | nobody, they never change | recruit questions, setup posts, info hub, ticket panels, `/family-links` | full size in galleries; the logo also as a thumbnail |
| **Clan logos and banners** | one each per family clan, `clan_data.logo` / `clan_data.banner` | `/clan upload` (bytes from a Discord attachment) or a pasted URL in the clan dashboard | `/todo` thumbnail (**the hot path**), clan dashboard thumbnail, `/family-links` gallery, `/clan list` | thumbnail size almost everywhere; full size rarely |
| **FWA base images** | two per Town Hall level, `fwa_data` document `fwa_config`, maps `war_base_images` / `active_base_images`, copied into `utils.constants` at startup | `/fwa upload-images` (bytes) or the FWA dashboard (from URL) | `/fwa bases`, new-TH upgrade flow, recruit questions | full resolution, rarely viewed |

Everything together is well under 1 GB. Storage is irrelevant; **egress and
request counts decide every option below.**

The current client, `utils/cloudinary_client.py`, exposes three calls:
`upload_image_from_url(url, folder, public_id)`, `upload_image_from_bytes(data,
folder, public_id)` and `delete_image(public_id)`, always with `overwrite=True,
invalidate=True`. The cloud name is hard-coded; the key and secret come from
`.env`. Those three calls are the whole integration surface, which is what
makes a swap cheap.

The bot also already attaches local files from disk: `assets/*_Footer.png`
(about 5 KB each) is referenced as `MediaItem(media="assets/Red_Footer.png")`
in 136 places, and hikari resolves the string as a `File` and uploads it with
every send and edit. Discord then hosts it. That is the pattern the static art
should follow.

## 2. Why the bandwidth went up

### 2.1 Originals used as thumbnails

`/todo` renders one `Section` per clan with `Thumbnail(media=clan_data.logo)`
(`extensions/commands/todo.py`, `_thumbnail_for`). That is the **original
upload**, whatever size the recruiter attached (`/clan upload` checks the
extension, not the size; Discord's own attachment limit is the only cap),
shown at roughly 80 px. No Cloudinary transformation
(`w_128,h_128,c_fill,f_auto,q_auto`) was ever applied, so every fetch moved
the full file. A 128 px WebP of the same logo is typically 5 to 15 KB. The
originals' sizes could not be measured from this sandbox (the Cloudinary
domain is egress-blocked here); check the Cloudinary usage report, which lists
bandwidth by asset.

### 2.2 hikari 2.3.5 downloads every image URL on every render

This is the part nobody knew. In hikari 2.3.5 the Components V2 builders hand
their media resource back as an upload candidate whether it is a local file or
an `https://` URL, and the REST payload builder uploads every candidate:

- `files.ensure_resource("https://…/logo.png")` returns a `files.URL`.
- `ThumbnailComponentBuilder.build()` and `MediaGalleryItemBuilder.build()`
  return `(payload, (media_resource,))` unconditionally
  (`hikari/impl/special_endpoints.py`).
- `RESTClientImpl._build_message_payload` puts every returned resource into
  the multipart form as `files[n]` (`hikari/impl/rest.py`), and at send time
  `files.URL.stream()` opens an `aiohttp.ClientSession` and **GETs the URL**.

Reproduced against the pinned wheel, one Section with a Cloudinary thumbnail,
built as an edit:

```text
hikari 2.3.5 | body attachments: [{'id': 0, 'filename': 'sample.png'}]
             | form resources: [('files[0]', 'URL')]
hikari 2.6.0 | body attachments: [] | form_builder: None
```

So on 2.3.5 the bot downloads the logo from Cloudinary, re-uploads it to
Discord as a hidden attachment (the component still points at the `https://`
URL, so the attachment is never shown), **and** Discord's media proxy fetches
the URL for display. Every send and every edit, with no caching anywhere:
`todo_data` caches the logo *map* for an hour, never the bytes.

Scope: every `Thumbnail(media=url)` and `MediaItem(media=url)` in the bot,
which is all 20 static URLs, the clan dashboard, `/clan list`,
`/family-links`, the ticket panels and `/todo`. The Supercell clan badges
`/todo` falls back to and the guild icon URLs are downloaded the same way (not
our bill, but latency on every render). Classic embeds are **not** affected:
`serialize_embed` already skipped `files.WebResource` in 2.3.5. Resources are
de-duplicated by URL within one message only.

Upstream fix: hikari 2.6.0 changelog, Bugfixes, "Do not fetch WebResource
attachments if they're part of components/embeds (#2687)", implemented as
`RESTClientImpl._filter_web_resources`.

### 2.3 The `/todo` cadence multiplies it

A DM panel edits itself every `REFRESH_INTERVAL_SECONDS` = 600 s for
`TTL_SECONDS` = 30 days (`utils/todo_sessions.py`). With hikari fetching the
originals on every edit:

```text
downloads/day per session = family clans shown × 144
```

Illustrative, not measured: ten active sessions showing five family clans is
7,200 downloads a day, about 216,000 a month, each the full original. At a
plausible 500 KB per logo that is roughly 100 GB a month against Cloudinary's
25 GB allowance, before Discord's own proxy fetches are counted. Whatever the
real sizes were, the shape is what matters: **originals × edits × sessions**.

### 2.4 Discord's own fetch

Discord documents that a media item `url` "supports arbitrary urls and
`attachment://<filename>`" and that the proxy fetch happens asynchronously
after create or edit. **Cache duration, whether origin `Cache-Control` is
honoured, and whether an edit re-fetches are not documented anywhere** (docs,
changelog, or the community reference). Treat it as at least one fetch per
unique URL per message, possibly more. This is another reason to prefer hosts
where reads are unmetered.

### 2.5 What the fix in flight has to keep

1. Never put an original in a thumbnail. Generate a small variant at upload
   time with Pillow (the bot already depends on it and already does exactly
   this for emojis in `update_clan_info.process_emoji_upload`) and store its
   URL next to the original.
2. Close the double-fetch (section 3). Until it is closed, every image URL on
   **any** host is downloaded by the bot on every edit; a small variant only
   makes that cheap, not free.
3. Cloudinary's free plan: 25 credits a month, one credit = 1 GB bandwidth, or
   1 GB storage, or 1,000 transformations; bandwidth is a rolling 30-day
   window; limits are soft (warnings at 90 %, nothing blocked at 100 %) but
   repeated overage auto-disables the account, with 30 days to restore before
   assets are deleted. The next paid tier starts at $89 a month. Survivable
   after 1 and 2, but still metered.

## 3. Closing the double-fetch: two ways

**A. Upgrade.** hikari 2.6.0 is the first release with the fix. The latest
lightbulb, 3.2.6, declares `hikari~=2.6.0`, so the coupled move is
**hikari 2.6.0 + hikari-lightbulb 3.2.6**. The "2.5.0 + 3.2.5" pair in
[hikari-lightbulb-versions.md](hikari-lightbulb-versions.md) is already
stale. This is its own project: lightbulb 3.0 to 3.2 API differences, and the
rate-limit behaviour re-check that document demands.

**B. Startup shim, validated on 2.3.5.** Mirrors the 2.6.0 fix at the builder
level, so URL media is no longer uploaded while local files and `Bytes` still
are. Install once at startup (before any command module builds a component)
and delete it with the upgrade:

```python
from hikari import files
from hikari.impl import special_endpoints as se


def _skip_web_resources(build):
    """hikari 2.3.5 uploads URL media as attachments; 2.6.0 does not (#2687)."""
    def wrapped(self):
        payload, resources = build(self)
        return payload, tuple(
            r for r in resources if not isinstance(r, files.WebResource)
        )
    return wrapped


se.ThumbnailComponentBuilder.build = _skip_web_resources(se.ThumbnailComponentBuilder.build)
se.MediaGalleryItemBuilder.build = _skip_web_resources(se.MediaGalleryItemBuilder.build)
```

Verified result on 2.3.5 for a Section with a Cloudinary thumbnail plus the
usual local footer: the thumbnail keeps its `https://` URL and is **not**
uploaded, `attachments` contains only `Red_Footer.png`, and the multipart form
carries one `File`. The builders are imported per module in about fifty files
(`from hikari.impl import … ThumbnailComponentBuilder as Thumbnail`), which is
why a patch of the two classes beats changing imports.

## 4. The options

### 4.1 Discord itself (no third party at all)

| Path | Verdict |
|---|---|
| **Attach from disk or memory** (`hikari.File` / `hikari.Bytes`) | Works today, already used for footers. Zero third-party bytes, no expiry, Discord hosts the copy. Costs one upload per send **and per edit**; on 2.3.5 an edit cannot re-reference an already uploaded file (`hikari.files.URL("attachment://…")` fails at form build, a bare string is treated as a local path, see `cards.py` `_standing_post_image_ref`). Hard limits: **10 files per message**, 10 MiB per file by default. Right for static art and base screenshots. **Wrong for `/todo`**: a page holds up to about twelve clan thumbnails (`COMPONENT_BUDGET` 38, three components per clan), more than ten files. |
| **Application emojis as thumbnails** | Up to **2,000 per application**, 256 KiB, 128×128, unsigned and therefore permanent CDN URLs: `https://cdn.discordapp.com/emojis/{id}.png?size=128` (`?size=` accepts powers of two from 16 to 4096). The dashboard's "Use Cloudinary Logo" button already produces one per clan from the logo, via Pillow, and stores `<:name:id>` in `clan_data.emoji`. Free, Discord-hosted, exactly thumbnail-sized. Caveats: 128 px ceiling; emoji and logo must be regenerated together; rendering a `cdn.discordapp.com/emojis/…` URL inside a `Thumbnail` is allowed by the "arbitrary url" rule but *untested*, so try one panel first. |
| **Asset channel** (upload once, reuse `cdn.discordapp.com/attachments/…`) | Attachment URLs are signed with "a preset expiry time" (the docs' example spans 14 days; community tooling reports about 24 h). Discord refreshes a URL passed *without* its query string in API fields, documented for embed URLs and avatar URLs, not explicitly for V2 media items. Refresh otherwise means re-fetching the message or the undocumented `POST /attachments/refresh-urls`. Deleting the message deletes the asset. More moving parts than R2 for no gain. |
| **Stickers** | 320×320, 512 KiB, five free guild slots. No. |

### 4.2 Cloudflare (free egress is the whole point)

| Product | Free allowance | Notes |
|---|---|---|
| **R2** | 10 GB-month storage, 1 M Class A ops, 10 M Class B ops (reads), **egress free** including via `r2.dev`, S3 API and Workers | Overage is billed, not stopped ($0.015/GB, $0.36 per million reads). A payment method very probably has to be on file to enable R2 (*unverified*; the docs speak of a checkout flow and possible card pre-authorisation). `r2.dev` public URLs are "not intended for production": variable rate limit in the hundreds of requests per second, no edge cache, no Cache Rules, overwrites visible immediately. A custom domain on a Cloudflare zone adds the CDN cache (then overwriting a key does **not** purge; use versioned keys) and unlocks transformations. Python: `boto3`/`aioboto3` with `endpoint_url="https://<ACCOUNT_ID>.r2.cloudflarestorage.com"`, `region_name="auto"`, an R2 API token as the key pair. |
| **Workers Static Assets** | "Requests to static assets are free and unlimited", not counted against the 100k/day Worker limit; 20,000 files, 25 MiB each; no card, no domain | Edge-cached, `_headers` file for long `max-age`. The catch: content is deploy-time. Uploading a new logo means a new deployment (Wrangler, or the REST manifest/upload/deploy flow from Python). Ideal for static art, awkward for `/clan upload`. |
| **Pages** | Same free/unlimited static requests; 500 builds/month | Marked legacy: every Pages doc now says to start new projects on Workers. `/cdn-cgi/image/` transformations fail on `pages.dev`. |
| **Image transformations** | **5,000 unique transformations/month free on any plan**; beyond that cached ones keep serving, new ones fail, nothing is charged | URL mode (`/cdn-cgi/image/width=128,format=auto/…`) needs a zone, i.e. a domain. Not available on `r2.dev`. Unnecessary if Pillow generates variants at upload, which it should. |
| **Domain** | Registrar at cost (.com about $10/yr per third-party trackers, *unverified*) | Optional. Turns R2 into a cached CDN with Cache Rules and transformations. |

### 4.3 Other object stores

| Provider | Free | Fit |
|---|---|---|
| **Oracle OCI Always Free** | 20 GB, **10 TB/month egress**, 50,000 API requests/month, S3-compatible endpoint, public buckets, strong consistency | Largest allowances anywhere. But: card required, notorious signup failures, accounts idle 30 days "may be deemed abandoned", and 50k requests a month is below what 2.3.5's double-fetch would generate (upgrade the tenancy to pay-as-you-go to lift it; the free amounts still apply, overage is cents). Runner-up. |
| **Tebi** | 25 GB (two copies), 250 GB/month transfer, S3 API, public bucket policies | No card during the trial, card afterwards; $0.01/GB out beyond. Small vendor. |
| **Backblaze B2** | 10 GB, egress free only up to **3× average stored** (about 0.6 GB/month at our size), 2,500 Class B/day; no card; spend caps available | Unlimited egress only through Cloudflare, which needs your own domain. Direct hotlinking at our volume would cost about $3/month at 300 GB. |
| **Google Cloud Storage** | 5 GiB (US regions), 55,000 ops, **100 GiB/month egress** from North America | Card required, overage billed; objects default to `Cache-Control: max-age=3600`. Fine if a card is acceptable. |
| **AWS S3** | New accounts (after 2025-07-15) get 6 months of credits, then the account closes unless upgraded; 100 GB/month data transfer out stays free for everyone | Not free storage after the trial; public access blocked by default. Skip. |
| **Azure Blob** | 100 GB/month egress free for all; storage free 12 months only | No S3 API. Skip. |
| Scaleway, Storj, Wasabi | Free tiers withdrawn (Scaleway Dec 2023, Storj Apr 2024); Wasabi suspends when egress exceeds storage | No. |
| Hetzner Object Storage (€4.99/month, 1 TB + 1 TB) / DigitalOcean Spaces ($5, CDN included) | Cheapest sensible paid options; Bunny Storage + CDN at about $1/month is cheaper still | Only if "free" turns out negotiable. |
| Filebase, Pinata (IPFS) | 5 GB / 1 GB with hard stops and small gateway request quotas; a changed file gets a new CID | No. |

### 4.4 Cloudinary look-alikes

| Service | Free | Overage | Fit |
|---|---|---|---|
| **ImageKit** | 20 GB bandwidth/month, unlimited URL transformations, no card, official `imagekitio` SDK; storage 20 GB per ImageKit, 3 to 5 GB per third-party trackers (*unresolved*) | **Hard stop** until the month resets | The closest drop-in. The hard stop is the same failure mode as today, so it only fits once the double-fetch is closed. Runner-up if URL transformations matter. |
| Uploadcare | 1 GB, 5 GB traffic, 1,000 operations (uploads and transforms count) | CDN delivery disabled | Too small. |
| Sirv | 500 MB, 2 GB transfer, unlimited transforms, gentlest overage (two months over before a freeze) | Freeze after grace | Too small. |
| Supabase Storage | 1 GB, 5 GB egress + 5 GB cached, transforms Pro-only | Grace, then HTTP 402 | **Free projects pause after one idle week**; the bot never touches its DB, so it would pause. No. |
| Appwrite | 2 GB, 5 GB bandwidth, transforms Pro-only | No add-ons | Paused after 7 days without console activity, deleted after 90. No. |
| Vercel Blob (Hobby) | 1 GB, 10 GB transfer | Blocked 30 days | Hobby is non-commercial only. No. |
| Filestack | 1 GB, 1 GB bandwidth, 1,000 transforms | Whole account locked | No. |
| Firebase Storage | Spark plan no longer gets a bucket; Blaze (card, pay-as-you-go) required | Billed | Use GCS directly if going that way. |
| Cloudimage, Gumlet, TwicPics, imgix | Cloudimage's free plan ended 2025-09-30; the others are origin-fetch resizers without storage, or trial-only | | No. |
| Bunny (paid) | $0.01/GB storage and CDN, $1/month minimum | | Cheapest paid fallback. |

### 4.5 Consumer image hosts

Imgur's terms forbid using it as a CDN, its app registration disappeared in
December 2025 and it is blocked in the UK. Postimages' terms say
"programmatic uploads are not allowed". Catbox treats app and CDN use as
commercial (approval required), purges idle anonymous files from 2026-07-06,
filters uploads from datacenter IPs (our VPS) and has a 2025 data-loss
incident. ImgBB, Freeimage.host and PixHost tolerate hotlinking but reserve
the right to delete anything without notice and have no API delete or
overwrite. Dropbox `raw=1` links work within 20 GB/day but pause for 24 h on
overage. **None is production-grade for this bot.**

### 4.6 GitHub, for static art only

The repository is public, so `https://cdn.jsdelivr.net/gh/SirRuggie/WU_Python@<commit>/assets/<file>`
is a permanent, free, unlimited-bandwidth CDN URL (20 MB per file, 150 MB per
repo snapshot, `@commit` cached forever, terms allow app assets). It costs the
bot nothing per send once the double-fetch is closed. It breaks the day the
repo goes private, which is the argument for attaching from `assets/` instead.
`raw.githubusercontent.com` serves `max-age=300` and returns 429s under
hotlink load; GitHub Releases redirect to a signed URL served as an attachment
(behaviour under Discord's proxy *untested*). Neither is better than jsDelivr.

## 5. Comparison of the real candidates

| | Free storage | Free reads / month | Free egress | Card | On overage | Code change | Fit |
|---|---|---|---|---|---|---|---|
| **Cloudflare R2** | 10 GB | 10 M | **unlimited** | very likely (*unverified*) | billed, small | swap the client for S3 calls | **best** |
| Discord attachments from `assets/` | n/a | n/a | n/a | no | n/a | change 20 URL strings to paths | **best for static art** |
| Application emoji URLs | 2,000 emojis | n/a | n/a | no | n/a | derive a URL from `clan_data.emoji` | best for `/todo` thumbnails, 128 px |
| Workers Static Assets | 20k files | unlimited | unlimited | no | n/a | deploy pipeline for uploads | static art; awkward for uploads |
| Oracle OCI | 20 GB | 50 k (free-only tenancy) | 10 TB | yes | free-only: cannot exceed; PAYG: cents | S3 calls | runner-up, painful signup |
| ImageKit | 3 to 20 GB | unlimited | 20 GB | no | **hard stop** | SDK swap | runner-up, same trap as today |
| GCS Always Free | 5 GiB | 55 k ops | 100 GiB | yes | billed | S3 calls with HMAC keys | fine with a card |
| Cloudinary (stay) | 25 credits shared | shared | 25 GB shared | no | soft, then account disabled | none | survivable after the fixes, still metered |

## 6. Recommendation

1. **Close the double-fetch first** (section 3). Ship the shim now; schedule
   the hikari 2.6.0 + lightbulb 3.2.6 upgrade as its own change. Nothing else
   in this document is safe on 2.3.5 without it.
2. **Never render an original as a thumbnail.** At upload, Pillow produces the
   original plus a `thumb` variant (≤ 256 px, WebP or PNG, tens of KB), stored
   as `clan_data.logo_thumb`. `/todo` and the clan dashboard use the
   variant. Optionally `/todo` uses the application emoji URL instead, which
   removes the last third-party fetch from the hottest path.
3. **Static art into `assets/`**, referenced as local paths exactly like the
   footers, with the GIFs re-encoded to sane sizes. Twenty string edits. Once
   on hikari 2.6.0, the heavy GIFs can switch to jsDelivr URLs to spare the
   upload per send if latency shows.
4. **Dynamic images on Cloudflare R2**, through `utils/media_store.py` with
   the same three calls as today plus the variant step. Start on the `r2.dev`
   URL; add `img.<domain>` later if a domain exists, for the edge cache.

Why R2 over the rest: it is the only free option whose reads are effectively
unmetered *and* that accepts runtime uploads through a standard S3 call. The
Discord-native paths cover the two places that actually matter for
bandwidth, so R2 only carries the rare full-size views.

**The zero-third-party variant**, if adding a Cloudflare account is not wanted:
keep the resized bytes in MongoDB (a `media` collection, one document per
image, well under the 16 MB document limit), attach them with `hikari.Bytes`
at render time, and use the application emoji URL for `/todo`. No account, no
card, no egress anywhere; the price is an upload per send and edit, a
ten-files-per-message ceiling on every view, and render sites that pass bytes
instead of URLs. Sound, but more code than the R2 swap.

## 7. Migration plan

**Phase 0, host-agnostic, small.** Install the shim at startup. Add the
thumbnail variant to `/clan upload` and the dashboard logo path; backfill
existing clans with a one-off script that downloads each `clan_data.logo`,
resizes, uploads and writes `logo_thumb`. Switch `/todo` to it. This alone
ends the incident on Cloudinary.

**Phase 1, static art.** Download the 20 assets once into `assets/` (or
`assets/art/`), re-encode oversized GIFs, replace the URL strings with paths.
Verify each panel renders. Remove the "cloudinary_icon.png" footer icons in
the upload confirmations at the same time.

**Phase 2, storage.** Create the R2 bucket with public access, an API token
with object read/write, and `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`,
`R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `R2_PUBLIC_BASE_URL` in `.env`. Write
`utils/media_store.py` (`aioboto3` or `boto3` in `run_in_executor`, keys with
extensions so `url_safety.is_safe_public_url` still accepts them), register
it in `main.py` where `CloudinaryClient` is registered, and migrate the
callers: `extensions/commands/clan/upload.py`,
`extensions/commands/fwa/upload_images.py`,
`extensions/commands/clan/dashboard/fwa_data.py`, and the dashboard emoji
path, which only needs a public URL. A migration script copies every URL
referenced in `clan_data` and `fwa_config` to R2 and rewrites the documents;
Cloudinary stays read-only for a week as a fallback.

**Phase 3, cleanup.** Remove `cloudinary` from `requirements.txt`, the two
`.env` keys, the "Cloudinary Issues" advice in `clan/upload.py`, the
"Use Cloudinary Logo" button label, and the mentions in `README.md`,
`deployment.md` and `backlog.md` (AUTH-002/003 still apply, they just name a
different store). Update `tests/test_component_error_responses.py` and the
`res.cloudinary.com` fixture in `tests/test_cards.py`.

## 8. Things to verify before deciding

- The Cloudinary usage report: bandwidth by asset and the request count.
  Expect the clan logos at the top; an `aiohttp` user agent in any request log
  confirms 2.2 in production.
- Sizes of the current originals (not measurable from the sandbox).
- Whether R2 really requires a payment method at signup.
- A `Thumbnail` rendering a `cdn.discordapp.com/emojis/…` URL.
- Whether Discord's proxy re-fetches on edit. Unknown, and irrelevant once
  reads are unmetered, but it decides how much the Cloudinary-side fix alone
  would have bought.

## 9. What is actually on Cloudinary (read-only inventory, 2026-09-02)

178 image assets, 184 MB, no videos or raw files. What the migration has to
know:

| Group on Cloudinary | Assets | Bytes | Migrate? |
|---|---|---|---|
| `clan_logos/Warriors_United` | 17 logos, 0.15 to 3.3 MB each | 17.1 MB | yes, driven by the Mongo rows |
| `clan_banners/Warriors_United` | 10 banners, 0.27 to 1.1 MB each | 5.0 MB | yes, driven by the Mongo rows |
| `FWA_Images/Warriors_United/war_bases` | 10 war bases, TH9 to TH18, 1.1 to 6.2 MB each | 37.4 MB | yes, driven by the Mongo rows |
| `FWA_Images/Warriors_United/active_bases` | 9 active bases; **TH10 has none** | 11.8 MB | yes, driven by the Mongo rows |
| `misc_images`, `server_banners`, root statics | 39 | 41 MB | no: the repo's `assets/branding/` copies feed `branding/` and the `*/static/` folders |
| legacy: `old_clan_*` (a prior 22-clan roster), `FWA_Images/Kings War Bases`, the `fwa/` tree, `clan_recruitment/disboard_reviews`, personal folders | 88 | 50 MB | no |

- **The account is over its limit.** Free plan, 45.8 of 25 credits used in
  the current period (183 %), all of it bandwidth: 49 GB. Cloudinary
  disables accounts that stay over after repeated notices, with 30 days
  before assets are deleted, so the migration is time-sensitive.
- 17 clans have a logo and 10 of those a banner. Whether all 17 are still
  family clans is Mongo's call, so per-clan folders come from Mongo during
  migration, not from this list.
- `server_banners` holds a newer 1397x466 set from 2025-11-15 (Criteria,
  Rules, Casual, Zen, FWA, AboutUs, OurClans, TrialClans, Competitive) that
  nothing in the code uses; the repo carries the older 1118x373 set.
- The repo's GIF copies are 3 to 4 times smaller than the Cloudinary
  originals (for example `WU_Strikes.gif`: 1.3 MB against 5.3 MB), so the
  repo, not Cloudinary, is the source for the static folders.
- Cloudinary is in dynamic-folder mode: 132 assets carry public_ids that
  no longer match their folder (`_archive/`, `old_clan_*` prefixes). The
  migration downloads the URLs Mongo holds, which embed the public_id, so
  folders are irrelevant; a public_id change on an active asset would
  break its URL, and the dry run surfaces that as a download failure.
- Sixteen byte-identical duplicates sit in the legacy folders; none are
  in scope.

The bucket `wu-media` now holds the agreed layout as empty placeholders:
`branding/logo/`, `branding/banners/`, `clans/`, `fwa/bases/<th>/` for the
thirteen Town Hall levels, `fwa/static/`, `recruit/static/`,
`recruit/strikes/`, `tickets/static/`. The code still writes the old
Cloudinary-shaped paths and is the next thing to update.

## Sources

hikari: [CHANGELOG 2.6.0](https://github.com/hikari-py/hikari/blob/master/CHANGELOG.md),
[PR #2687](https://github.com/hikari-py/hikari/pull/2687),
[2.3.5 `rest.py`](https://github.com/hikari-py/hikari/blob/2.3.5/hikari/impl/rest.py),
[2.3.5 `special_endpoints.py`](https://github.com/hikari-py/hikari/blob/2.3.5/hikari/impl/special_endpoints.py),
[hikari on PyPI](https://pypi.org/project/hikari/),
[hikari-lightbulb on PyPI](https://pypi.org/project/hikari-lightbulb/).
Discord: [Unfurled media item](https://discord.com/developers/docs/components/reference#unfurled-media-item),
[signed attachment CDN URLs](https://discord.com/developers/docs/reference#signed-attachment-cdn-urls),
[editing message attachments](https://discord.com/developers/docs/reference#editing-message-attachments),
[application-owned emoji](https://discord.com/developers/docs/resources/emoji#emoji-object-applicationowned-emoji),
[image formatting](https://discord.com/developers/docs/reference#image-formatting),
[uploading files](https://discord.com/developers/docs/reference#uploading-files),
[discord-api-docs #4782](https://github.com/discord/discord-api-docs/issues/4782),
[discord-api-docs #7529](https://github.com/discord/discord-api-docs/issues/7529).
Cloudinary: [credits FAQ](https://cloudinary.com/documentation/developer_onboarding_faq_credits),
[quota counting](https://support.cloudinary.com/hc/en-us/articles/203125631-How-does-Cloudinary-count-my-plan-s-quotas-and-what-does-every-quota-mean),
[exceeding limits](https://support.cloudinary.com/hc/en-us/articles/202521702-What-happens-if-I-exceed-plan-limits-),
[disabled accounts](https://cloudinary.com/documentation/ts_why_is_my_account_disabled_and_how_can_i_recover_my_disabled_account),
[billing and plans](https://cloudinary.com/documentation/billing_and_plans).
Cloudflare: [R2 pricing](https://developers.cloudflare.com/r2/pricing/),
[R2 limits](https://developers.cloudflare.com/r2/platform/limits/),
[public buckets](https://developers.cloudflare.com/r2/buckets/public-buckets/),
[boto3 example](https://developers.cloudflare.com/r2/examples/aws/boto3/),
[Workers limits](https://developers.cloudflare.com/workers/platform/limits/),
[static assets billing](https://developers.cloudflare.com/workers/static-assets/billing-and-limitations/),
[static assets direct upload](https://developers.cloudflare.com/workers/static-assets/direct-upload/),
[Pages limits](https://developers.cloudflare.com/pages/platform/limits/),
[Images pricing](https://developers.cloudflare.com/images/pricing/),
[transformations overview](https://developers.cloudflare.com/images/optimization/transformations/overview/),
[Registrar](https://developers.cloudflare.com/registrar/).
Object stores: [Oracle Always Free resources](https://docs.oracle.com/en-us/iaas/Content/FreeTier/freetier_topic-Always_Free_Resources.htm),
[Oracle price list](https://www.oracle.com/cloud/price-list/),
[Tebi FAQ](https://tebi.io/faq.html),
[Backblaze pricing](https://www.backblaze.com/cloud-storage/pricing),
[Backblaze via Cloudflare](https://www.backblaze.com/docs/cloud-storage-deliver-public-backblaze-b2-content-through-cloudflare-cdn),
[Google Cloud free tier](https://docs.cloud.google.com/free/docs/free-cloud-features),
[AWS free tier FAQ](https://aws.amazon.com/free/free-tier-faqs/),
[AWS 100 GB data transfer](https://aws.amazon.com/blogs/aws/aws-free-tier-data-transfer-expansion-100-gb-from-regions-and-1-tb-from-amazon-cloudfront-per-month/),
[Azure bandwidth pricing](https://azure.microsoft.com/en-us/pricing/details/bandwidth/),
[Storj free tier discontinued](https://forum.storj.io/t/discontinuation-of-the-storj-free-tier/25332),
[jsDelivr README](https://github.com/jsdelivr/jsdelivr).
Look-alikes: [ImageKit plans](https://imagekit.io/plans/),
[Uploadcare pricing](https://uploadcare.com/pricing/),
[Sirv pricing](https://sirv.com/pricing/),
[Supabase pricing](https://supabase.com/pricing),
[Supabase project pausing](https://supabase.com/docs/guides/platform/free-project-pausing),
[Appwrite pricing](https://appwrite.io/pricing),
[Vercel Blob pricing](https://vercel.com/docs/vercel-blob/usage-and-pricing),
[Firebase Storage plan change](https://firebase.google.com/docs/storage/faqs-storage-changes-announced-sept-2024),
[Cloudimage Q3 2025](https://www.cloudimage.io/new-q3-2025),
[Bunny CDN pricing](https://docs.bunny.net/cdn/pricing).
Consumer hosts: [ImgBB API](https://api.imgbb.com/),
[ImgBB terms](https://imgbb.com/tos),
[Imgur registration removed (Tautulli #2620)](https://github.com/Tautulli/Tautulli/issues/2620),
[Imgur UK block](https://eandt.theiet.org/2025/09/30/imgur-blocks-uk-users-risking-chaos-sites-relying-its-image-hosting),
[Catbox FAQ](https://catbox.moe/faq.php),
[Catbox idle uploads](https://blog.catbox.moe/post/821058172332769280/removing-idle-uploads),
[Catbox datacenter filtering](https://blog.catbox.moe/post/809324731954266112/missing-files-blank-uploads-commercial),
[Postimages terms](https://postimages.org/terms),
[Dropbox banned links](https://help.dropbox.com/share/banned-links).
