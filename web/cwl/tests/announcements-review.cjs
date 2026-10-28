const { chromium } = require("playwright");
const fs = require("fs");
const base = process.env.PREVIEW_URL || "http://127.0.0.1:8955";
const out = process.env.REVIEW_DIR || "/tmp/wu-announcements";
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const context = await browser.newContext({
    viewport: { width: 360, height: 800 },
  });
  const errors = [],
    blocked = [],
    writes = [];
  await context.route("**/*", (r) => {
    let u = new URL(r.request().url());
    if (u.origin === base) return r.continue();
    if (["data:", "blob:"].includes(u.protocol)) return r.continue();
    blocked.push(u.origin + u.pathname);
    return r.abort();
  });
  const page = await context.newPage();
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (r.method() !== "GET") writes.push({ method: r.method(), url: r.url() });
  });
  page.on("dialog", (d) =>
    d.type() === "beforeunload" ? d.accept() : d.dismiss(),
  );
  async function open(sid) {
    await page.goto(`${base}/?view=publication&step=announce&season=${sid}`);
    await page
      .locator(".fixture-button, .manage-cycle-fields")
      .first()
      .waitFor();
    if (
      await page
        .getByRole("button", { name: "Open local test session" })
        .count()
    )
      await page
        .getByRole("button", { name: "Open local test session" })
        .click();
    await page.locator(".manage-cycle-fields").waitFor();
    await page.waitForTimeout(150);
  }
  async function shot(name) {
    await page.screenshot({ path: `${out}/${name}.jpg`, quality: 80 });
  }
  await open(1);
  await shot("01-unlinked");
  await open(2);
  await page
    .locator(".announcement-pool-cards")
    .evaluate((e) => window.scrollBy(0, e.getBoundingClientRect().top - 80));
  await shot("02-pools");
  await page.getByRole("button", { name: "Edit", exact: true }).first().click();
  await page.locator(".announcement-edit-panel").waitFor();
  await shot("03-edit");
  const initialFocus = await page.evaluate(() => ({
    text: document.activeElement?.textContent,
    aria: document.activeElement?.getAttribute("aria-label"),
  }));
  await open(2);
  await page
    .getByRole("button", { name: "Review and send", exact: true })
    .click();
  await page.locator(".announcement-send-review").waitFor();
  await shot("04-review");
  await page.getByRole("button", { name: "Cancel", exact: true }).click();
  await open(3);
  await page
    .locator(".announcement-pool-cards")
    .evaluate((e) => window.scrollBy(0, e.getBoundingClientRect().top - 80));
  await shot("05-older");
  await open(2);
  await page.getByText("Clan roster images & testing", { exact: true }).click();
  await page.locator(".clan-roster-images select").waitFor();
  await page.locator(".clan-roster-images").scrollIntoViewIfNeeded();
  await shot("06-images");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await open(2);
  await shot("07-desktop");
  const styles = await page
    .locator(".announcement-pool-card")
    .first()
    .evaluate((el) =>
      [
        el.querySelector("h3"),
        el.querySelector(".announcement-pool-status"),
        el.querySelector(".announcement-muted"),
      ].map((e) => {
        const c = getComputedStyle(e);
        return {
          text: e.textContent,
          color: c.color,
          fill: c.webkitTextFillColor,
          font: c.fontSize,
          background: getComputedStyle(el).backgroundColor,
        };
      }),
    );
  await open(5);
  const hidden = await page.locator(".announcement-toolbar").innerText();
  await open(4);
  const uncertain = await page.locator(".announcement-pool-cards").innerText();
  const state = await (await context.request.get(base + "/qa/state")).json();
  if (JSON.stringify(state.baseline) !== JSON.stringify(state.current))
    throw new Error("Fixture counts changed");
  if (writes.some((r) => !r.url.endsWith("/dev/login")))
    throw new Error("Unexpected mutation " + JSON.stringify(writes));
  if (errors.length) throw new Error(errors.join("\n"));
  fs.writeFileSync(
    `${out}/browser-evidence.json`,
    JSON.stringify(
      {
        initialFocus,
        styles,
        hidden,
        uncertain,
        errors,
        blocked,
        writes,
        state,
      },
      null,
      2,
    ),
  );
  console.log(
    JSON.stringify({
      initialFocus,
      styles,
      errors,
      blocked,
      countsUnchanged: true,
    }),
  );
  await browser.close();
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
