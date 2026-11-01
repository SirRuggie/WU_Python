# Base bank

Signed-in members can open `/bases`, choose a Town Hall, and open the stored
Clash layout link with Copy base. Plain keys are merged defenses; `_new` keys are
non-merged. Cards use war-base images without cropping. Missing links have no
copy action, missing images have a reserved neutral placeholder, and empty levels
are omitted. Default selection uses the existing shared linked-account loader,
independently of a previous CWL signup visit; explicit choices win over late reads.

The one authenticated GET endpoint `/api/cwl/bases` reads existing `fwa_config`
through an allowlisted projection and caches it for 30 seconds. `?level=th18`
returns only that base's public information/upgrade notes when Details opens.
These are rendered as plain text. There are no writes or schema changes. The
supported key constant moved to a shared utility without changing its values;
existing Manage and bot labels/behavior are unchanged. No bot restart is needed.

Reused the existing API/error and account-display loaders, dashboard navigation,
semantic icon renderer, Mongo lifecycle, native disclosures and theme controls.
No new Discord identity renderer or parallel avatar helper was introduced.

Validation covers member/anonymous access even with a warm cache, output field
allowlist, all supported variant mappings, invalid Clash URLs, empty/malformed
config, absent link/image, lazy details, external text, late account defaults,
explicit selection, unavailable/denied reads, and clean routing. Full frontend,
TypeScript/build and relevant network-isolated backend suites run for this change.
Behavioral mutants swap variants, expose a staff field, and render a missing-link
copy action; each must fail its regression.

Isolated static browser checks cover 320/360/390/1440 widths, stacked/two-column
cards, 44px targets, no document overflow, contained lazy images, zero details
reads before expansion, TH changes, missing data, empty/error/denied states and
plain-text details. Screenshots at360/1440 are visually inspected. Sample SVG base
layouts are test-only illustrations, not actual FWA base recommendations. No
production link was opened; fixture checks do not prove live game import,
Discord OAuth, real-phone behavior or a complete assistive-technology audit.
