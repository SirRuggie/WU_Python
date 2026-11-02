const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const crypto = require("crypto");
const phase = process.argv[3] || "after";
if (!["before", "after"].includes(phase) || !process.argv[2])
  throw new Error(
    "Usage: node tests/exports-plain.browser.cjs FIXTURE_EVIDENCE_DIR [before|after] [OUTPUT_DIR]",
  );
const evidence = path.resolve(process.argv[2]);
const ready = JSON.parse(fs.readFileSync(path.join(evidence, "ready.json")));
if (
  !Number.isInteger(ready.port) ||
  ready.port < 1024 ||
  [8766, 8767, 27017, 27166].includes(ready.port)
)
  throw new Error("Only an isolated loopback fixture port is allowed");
const origin = `http://127.0.0.1:${ready.port}`;
const out = path.resolve(
  process.argv[4] || path.join(path.dirname(evidence), `browser-${phase}`),
);
if (fs.existsSync(path.join(out, "proof.json")))
  throw new Error("Use a fresh output directory to preserve earlier evidence");
fs.mkdirSync(out, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    acceptDownloads: true,
  });
  const page = await context.newPage();
  const requests = [];
  const blocked = [];
  await context.route("**/*", async (route) => {
    const u = route.request().url();
    if (u.startsWith(origin) || u.startsWith("blob:") || u.startsWith("data:"))
      return route.continue();
    blocked.push({ url: u, type: route.request().resourceType() });
    if (route.request().resourceType() === "image")
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#52739a"/></svg>',
      });
    return route.abort();
  });
  page.on("request", (r) => {
    if (r.url().includes("/api/cwl/"))
      requests.push({ method: r.method(), url: r.url() });
  });
  await page.request.post(origin + "/_exports/mode", {
    data: { preview_error: 0, download_error: 0 },
  });
  await page.goto(origin + "/cwl/exports");
  await page.getByRole("button", { name: "Open local test session" }).click();
  await page.locator(".export-record").first().waitFor();
  const season = page.locator(".season-choice select");
  if ((await season.inputValue()) !== "2")
    throw new Error("Direct route did not select current available season");
  const saved = {};
  for (const [kind, basis] of [
    ["accounts", "current"],
    ["accounts", "published"],
    ["participation", "current"],
    ["participation-history", "current"],
    ["bonus-history", "current"],
  ]) {
    if (
      (await page.locator(".export-controls select").first().inputValue()) !==
      kind
    )
      await page.locator(".export-controls select").first().selectOption(kind);
    if (
      kind === "accounts" &&
      (await page.locator(".export-controls select").nth(1).inputValue()) !==
        basis
    )
      await page.locator(".export-controls select").nth(1).selectOption(basis);
    await page.locator(".export-record").first().waitFor();
    await page
      .getByRole("button", { name: "Download CSV", exact: true })
      .waitFor({ state: "visible" });
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.getByRole("button", { name: "Download CSV", exact: true }).click(),
    ]);
    const file = path.join(out, `${kind}-${basis}.csv`);
    await download.saveAs(file);
    const raw = fs.readFileSync(file);
    const baseline = fs.readFileSync(
      path.join(evidence, `${kind}-${basis}.csv`),
    );
    if (!raw.equals(baseline)) throw new Error(`CSV mismatch ${kind}/${basis}`);
    saved[`${kind}-${basis}`] = {
      sha256: crypto.createHash("sha256").update(raw).digest("hex"),
      bytes: raw.length,
    };
  }
  const layouts = [];
  await page
    .locator(".export-controls select")
    .first()
    .selectOption("accounts");
  await page.locator(".export-record").first().waitFor();
  const capture = async (state) => {
    for (const width of [360, 1440]) {
      await page.setViewportSize({ width, height: width === 360 ? 800 : 1000 });
      await page.waitForTimeout(450);
      await page.screenshot({
        path: path.join(out, `${state}-${width}.png`),
        fullPage: true,
      });
      const geometry = await page.evaluate(() => ({
        scroll: document.documentElement.scrollWidth,
        viewport: innerWidth,
      }));
      if (geometry.scroll > geometry.viewport)
        throw new Error("Overflow" + JSON.stringify(geometry));
      const targets = await page
        .locator(
          ".export-workspace button, .export-workspace select, .export-workspace input, .export-workspace summary",
        )
        .evaluateAll((elements) =>
          elements
            .map((element) => element.getBoundingClientRect())
            .filter((rect) => rect.width && rect.height)
            .map((rect) => ({ width: rect.width, height: rect.height })),
        );
      if (targets.some((rect) => rect.width < 44 || rect.height < 44))
        throw new Error(
          "Small export control target: " + JSON.stringify(targets),
        );
      layouts.push({
        state,
        width,
        ...geometry,
        minimumControlHeight: Math.min(...targets.map((rect) => rect.height)),
      });
    }
  };
  await capture("roster");
  const details = page.locator(".export-about summary");
  await details.focus();
  await page.keyboard.press("Enter");
  if (
    !(await page.locator(".export-about").evaluate((element) => element.open))
  )
    throw new Error("Keyboard disclosure did not open");
  await page.keyboard.press("Enter");
  if (phase === "after") {
    if (
      (await page.locator(".export-workspace h1").textContent()) !== "Exports"
    )
      throw new Error("Wrong title");
    if (
      !(await page
        .locator(".export-workspace")
        .getByText("179k", { exact: true })
        .count())
    )
      throw new Error("Weight not compact");
    if (
      !(await page
        .getByText("CWL month November 2026", { exact: true })
        .count())
    )
      throw new Error("Month not formatted");
    await season.selectOption("1");
    await page.getByText("0 rows ready", { exact: true }).waitFor();
    if (
      !(await page
        .getByRole("button", { name: "Download CSV", exact: true })
        .isDisabled())
    )
      throw new Error("Zero rows download enabled");
    await capture("empty");
    await season.selectOption("2");
    await page.locator(".export-record").first().waitFor();
    await page
      .getByRole("button", { name: "Results & participation", exact: true })
      .last()
      .click();
    await page.locator(".participation-workspace").waitFor();
    await page.goBack();
    await page.locator(".export-workspace").waitFor();
    if ((await season.inputValue()) !== "2")
      throw new Error("Back lost chosen season");
    await page.request.post(origin + "/_exports/mode", {
      data: { download_error: 500 },
    });
    await page
      .getByRole("button", { name: "Download CSV", exact: true })
      .click();
    await page
      .getByRole("alert")
      .filter({ hasText: "Download failed." })
      .waitFor();
    if (
      !(await page.getByRole("button", { name: "Retry", exact: true }).count())
    )
      throw new Error("Missing retry");
    await capture("download-error");
    await page.request.post(origin + "/_exports/mode", {
      data: { download_error: 0 },
    });
    await page.getByRole("button", { name: "Retry", exact: true }).focus();
    const [d] = await Promise.all([
      page.waitForEvent("download"),
      page.keyboard.press("Enter"),
    ]);
    await d.saveAs(path.join(out, "retry.csv"));
    if (
      !fs
        .readFileSync(path.join(out, "retry.csv"))
        .equals(fs.readFileSync(path.join(evidence, "accounts-current.csv")))
    )
      throw new Error("Retry CSV changed");
    await page.request.post(origin + "/_exports/mode", {
      data: { download_error: 403 },
    });
    await page
      .getByRole("button", { name: "Download CSV", exact: true })
      .click();
    await page
      .getByText("You do not have access to this export.", { exact: true })
      .waitFor();
    if (await page.getByRole("button", { name: "Retry", exact: true }).count())
      throw new Error("Denied retry shown");
    await capture("denied");
    await page.request.post(origin + "/_exports/mode", {
      data: { download_error: 0 },
    });
  }
  fs.writeFileSync(
    path.join(out, "proof.json"),
    JSON.stringify(
      {
        phase,
        passed: true,
        saved,
        layouts,
        requests,
        blocked_external: blocked,
        mutations: requests.filter(
          (r) => r.method !== "GET" && !r.url.endsWith("/dev/login"),
        ),
        production_writes: false,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      phase,
      passed: true,
      saved,
      layouts,
      blocked: blocked.length,
    }),
  );
  await browser.close();
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
