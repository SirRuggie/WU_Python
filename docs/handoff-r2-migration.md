# Handoff: finish the Cloudinary to Cloudflare R2 move

Written 2026-09-02 at the end of a cloud session that could not reach
Cloudinary's image host, MongoDB or the new bucket hostname. Everything
below is what a local session needs to finish the job. Delete this file in
the cleanup step at the end.

## Read first

- `.claude/rules/orchestration.md` loads automatically: the main session
  orchestrates and delegates to the agents in `.claude/agents/` (`scout`,
  `researcher`, `builder`, `refuter`, `debugger`). Reasoning in
  `docs/agent-orchestration.md`.
- `docs/media-hosting.md`: why we moved, the design, section 9 is the
  Cloudinary inventory. `docs/deployment.md`, section "Cloudflare R2 (image
  uploads)": setup and the migration runbook.
- Repo rules: no `sed -i` / `awk` / `perl -pi` (`docs/editing-this-repo.md`);
  never add Co-Authored-By or Claude-Session trailers to commits; the owner
  deploys to the server himself, never ssh to it; never paste a secret into
  chat, read them from `.env`.

## Where things stand

**Branch** `claude/cloudinary-alternatives-nymq6p`, rebased on main
(`74efd85`, which moved static art into the repo and size-caps Cloudinary
URLs at render time). Commits on the branch, oldest first: the research doc;
the R2 move (`utils/media_store.py`, `utils/media_urls.py`,
`utils/image_fetch.py`, `tools/migrate_media_to_r2.py`, tests, docs, the
`cloudinary` package removed, `boto3` added); the orchestration rule and
agents; the inventory; the layout update (upload commands and the migration
script write `clans/<Name>/logo|banner` and `fwa/bases/<th>/war|active`,
and `assets/` mirrors the bucket). Tests: 1208 pass; the one failure,
`tests/test_band_monitor.py::test_poll_failures_are_visible_throttled_and_log_recovery`,
fails identically on main and is unrelated.

**The layout commit has had no refuter pass yet.** The builder's own
verification and a second independent run of the greps, the asset-path
check, compile and the test suite all came back clean, but nobody has read
the diff adversarially. Do that first.

**R2**: account `d2b2bdb589030d8ddd698e2f62af5dc5`, bucket `wu-media`,
default jurisdiction (the plain `r2.cloudflarestorage.com` endpoint, not
`.us.`). Custom domain `https://wu-media.ruggie.zone` is Active and Enabled;
the `r2.dev` development URL stays off. The bucket holds 25 zero-byte folder
placeholders and nothing else:

```text
branding/logo/  branding/banners/
clans/
fwa/bases/th9 … th18, th16_new, th17_new, th18_new/  fwa/static/
recruit/static/  recruit/strikes/
tickets/static/
```

The owner was enabling **Images > Transformations** for the zone
`ruggie.zone` when the session ended; confirm it is on before setting
`R2_IMAGE_TRANSFORMS=true`. A **temporary** Account API token (Object Read &
Write, scoped to `wu-media`) is still active and is meant for the uploads
below; the owner has its Access Key ID and Secret. It must be revoked when
the uploads are done, and the bot gets its own token.

**Cloudinary**: cloud `dxmtzuomk`, free plan, at 183 % of its credits (49 GB
bandwidth) so the account may be disabled by Cloudinary at any time. The
Cloudinary MCP connector is available in a local session; use it read-only.
Inventory: 17 clan logos, 10 clan banners, 10 war bases, 9 active bases (TH10
missing) are the only assets the bot references; 127 others are static art
already in the repo or legacy content that must not move.

## Decisions already made

- Layout as above; per-clan folders are created by the migration from the
  clan names in Mongo, not from Cloudinary's list.
- The wide clan image is called `banner`, matching the bot everywhere.
- Static art comes from the repo (`assets/…`), whose copies are three to four
  times smaller than the Cloudinary originals, never from Cloudinary.
- Uploaded images get content-hashed keys (`logo.<sha256[:10]>.png`) and an
  immutable one-year Cache-Control; static art gets plain names.
- Cloudinary stays read-only until every row has moved; the code still
  rewrites Cloudinary URLs through `utils/cloudinary_urls.py` meanwhile.
- `R2_PUBLIC_BASE_URL=https://wu-media.ruggie.zone`.

## Next steps, in order

0. **Local `.env`** (gitignored, repo root), never in chat: `R2_ACCOUNT_ID`,
   `R2_ACCESS_KEY_ID` and `R2_SECRET_ACCESS_KEY` from the temporary token,
   `R2_BUCKET=wu-media`, `R2_PUBLIC_BASE_URL=https://wu-media.ruggie.zone`,
   `R2_IMAGE_TRANSFORMS=true` only once the zone toggle is confirmed, and
   `MONGODB_URI` with the same value the server uses. Create a venv and
   `pip install -r requirements.txt -r requirements-dev.txt` (boto3 is new).
1. **Refuter** over the layout commit (`git show HEAD` at the branch tip
   before this handoff was added). Fix anything it finds via the builder.
2. **Upload the static art** with the temporary token. Have the builder
   write `tools/upload_static_media.py`: walk `assets/branding`,
   `assets/fwa/static`, `assets/recruit`, `assets/tickets`; the key is the
   repo path without the `assets/` prefix (`branding/logo/WU_Logo.png`);
   plain names; `ContentType` from `utils.media_store.detect_image`;
   `Cache-Control: public, max-age=86400`; skip unchanged files (compare the
   local sha256 with object metadata); `--dry-run` flag; reuse
   `MediaStore` config loading. Run it. The code does not reference these
   URLs yet; they matter once the hikari double-fetch is fixed.
3. **Deploy before migrating**, so the server renders R2 URLs size-capped
   from the first minute: merge the branch into `main`, then hand the owner
   the runbook in `docs/deployment.md` (bot token into the server `.env`
   with the five `R2_*` lines, `git pull`, `pip install -r
   requirements.txt`, restart). The boot log must not say
   `[WARN] R2 is not configured`.
4. **Migrate**: `python tools/migrate_media_to_r2.py --dry-run`, read the
   list (a `FAILED` download means a Cloudinary public_id was renamed; fix
   that row by hand), then run it for real. Restart the bot so the FWA base
   maps reload. Check a `/todo` panel, the clan dashboard, `/clan list`,
   `/fwa bases`. With transformations on, delivery URLs look like
   `https://wu-media.ruggie.zone/cdn-cgi/image/width=256,fit=scale-down,format=auto/clans/<Name>/logo.<hash>.png`.
5. **Cleanup, a separate commit after a quiet week**: delete
   `utils/cloudinary_urls.py`, `tests/test_cloudinary_urls.py` and the
   Cloudinary branch in `utils/media_urls.py`; remove the two `CLOUDINARY_*`
   keys from the server `.env`; revoke the temporary R2 token; delete the
   Cloudinary account; delete this file.
6. **Separate change**: the hikari 2.3.5 double-fetch (`docs/media-hosting.md`
   section 3), by the validated startup shim or the coupled upgrade to
   hikari 2.6.0 + lightbulb 3.2.6.

## Open decisions for the owner

- TH10 has no active-base image; upload one or accept the gap.
- Cloudinary holds a newer 1397x466 server-banner set (Criteria, Rules,
  Casual, Zen, FWA, AboutUs, OurClans, TrialClans, Competitive) that nothing
  uses; the bot shows the older 1118x373 set. Replace or ignore.

## Gotchas

- `utils/url_safety.is_safe_public_url` demands an image extension in the
  URL path; R2 keys carry one, so pasted R2 URLs pass.
- `MediaStore._s3` disables botocore's newer request checksums; R2
  documents Content-MD5 for PutObject and not those headers.
- Cloudinary is in dynamic-folder mode: 132 assets have public_ids that no
  longer match their folder. The migration downloads the URLs Mongo holds,
  so folders are irrelevant, but a renamed active asset is a dead URL.
- `/clan upload-images` deletes the previous R2 object of a replaced image
  (`MediaStore.delete_url`); the first upload after migration deletes
  nothing because the old URL is Cloudinary's.
- The cloud session's scratch files are gone; everything needed is in the
  repo and in this file.
