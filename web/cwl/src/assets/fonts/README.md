# WU Inter

The dashboard loads one self-hosted Latin variable font, renamed **WU Inter**.
The weight axis is limited to 400–700; there is no italic face.

- Source: [`@fontsource-variable/inter` 5.3.0](https://registry.npmjs.org/@fontsource-variable/inter/-/inter-5.3.0.tgz), `files/inter-latin-wght-normal.woff2` (Inter v20 metadata).
- License: [OFL.txt](./OFL.txt), retained from that package. The license does not declare a Reserved Font Name; the subset nevertheless uses a unique family name.
- Input: 48,256 bytes, SHA256 `3100e775e8616cd2611beecfa23a4263d7037586789b43f035236a2e6fbd4c62`.
- Output: 30,572 bytes, SHA256 `24849c23f971eea16e36a35a02b4030ef5574729cec93add896fec156b037afe`.
- Processing: fontTools 4.68.0 `varLib.instancer` restricts `wght` to 400–700; serialize/reopen, then `fontTools.subset` retains the Latin unicode range declared in `tokens.css`, including its layout-feature closure. Font name records use WU Inter. Brotli 1.2.1 writes WOFF2.

`tokens.css` references the file by relative URL so Vite emits a hashed asset.
The additional **WU Inter Fallback** face uses local Arial and makes no network
request. Its size adjustment matches x-height: Inter 1118/2048 divided by Arial
1062/2048 = 105.27307%. Inter ascent 1984, descent 494 and zero line gap are then
divided by that adjustment for the fallback overrides.

Arial's reference metrics come from the published
[`@capsizecss/metrics` 3.6.2 Arial entry](https://unpkg.com/@capsizecss/metrics@3.6.2/entireMetricsCollection/arial/index.mjs).
These are reference-face metrics, not a measurement of every installed Arial
version or a guarantee of identical glyph widths. Browser font-loading and
layout checks provide the evidence for the actual dashboard environment.
