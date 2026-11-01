/* Isolated StrikesPreview fixture; no production calls or writes. */
const assert = require("node:assert/strict");
const { mkdirSync } = require("node:fs");
const { chromium } = require("playwright");
const path = require("node:path");

const origin = "http://127.0.0.1:8998";
const shots = "/tmp/wu-strike-tracking-qa/screenshots";
mkdirSync(shots, { recursive: true });

async function checkWidth(browser, width) {
  const page = await browser.newPage({
    viewport: { width, height: width === 360 ? 800 : 1000 },
    reducedMotion: "reduce",
  });
  const external = [];
  const writes = [];
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.origin !== origin) external.push(request.url());
    if (request.method() !== "GET")
      writes.push(`${request.method()} ${url.pathname}`);
  });
  await page.route("**/*", (route) => {
    if (new URL(route.request().url()).origin === origin)
      return route.continue();
    return route.abort();
  });
  try {
    await page.goto(`${origin}/strikes-preview.html`, {
      waitUntil: "domcontentloaded",
    });
    const tracking = page.locator(".strikes-tracking");
    await tracking.locator("summary").click();
    await tracking.getByText("Warriors United FWA").waitFor();
    assert.match(
      await tracking.locator("summary").innerText(),
      /1 on track · 1 behind · 1 private · 1 error · 1 unverified/,
    );
    for (const label of [
      "On track",
      "Behind",
      "War log private",
      "Error",
      "Unverified",
    ]) {
      assert(
        (await tracking.getByText(label, { exact: true }).count()) >= 1,
        `missing ${label}`,
      );
    }
    assert.equal(await tracking.locator(".strikes-tracking-clan").count(), 5);
    const geometry = await page.evaluate(() => ({
      width: innerWidth,
      document: document.documentElement.scrollWidth,
      body: document.body.scrollWidth,
    }));
    assert(
      geometry.document <= geometry.width + 1,
      `${width}: document overflow ${JSON.stringify(geometry)}`,
    );
    assert(
      geometry.body <= geometry.width + 1,
      `${width}: body overflow ${JSON.stringify(geometry)}`,
    );
    const textSizes = await tracking
      .locator("small, .strikes-tracking-state")
      .evaluateAll((nodes) =>
        nodes.map((node) => Number.parseFloat(getComputedStyle(node).fontSize)),
      );
    assert(
      textSizes.every((size) => size >= 12),
      `${width}: tracking text below 12px: ${textSizes}`,
    );
    await page.screenshot({
      path: path.join(shots, `${width}-strike-tracking.png`),
      fullPage: true,
    });
    await page.getByLabel("Activity actions").click();
    await page.getByRole("button", { name: "Find war" }).click();
    await page
      .getByText("War ended before final check: review in Find war")
      .waitFor();
    const warsText = await page.locator(".strikes-war-results").innerText();
    assert(warsText.includes("Clash API"), warsText);
    assert(warsText.includes("ClashKing (import)"), warsText);
    assert(warsText.includes("No automatic strikes"), warsText);
    assert.deepEqual(external, [], `${width}: external requests`);
    assert.deepEqual(writes, [], `${width}: unexpected writes`);
    return { width, geometry, trackingRows: 5 };
  } finally {
    await page.close();
  }
}

(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    const results = [];
    for (const width of [360, 1440])
      results.push(await checkWidth(browser, width));
    console.log(JSON.stringify({ ok: true, results, shots }));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
