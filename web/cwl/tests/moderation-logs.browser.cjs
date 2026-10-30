/* Browser checks against an isolated SQLite/Mongo/Discord moderation fixture. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { chromium } = require("playwright");

const port = Number(process.argv[2] || 8983);
assert(Number.isInteger(port) && port >= 8900 && port <= 8999);
const origin = `http://127.0.0.1:${port}`;
const shots = process.env.WU_LAYOUT_SCREENSHOTS;
if (shots) fs.mkdirSync(shots, { recursive: true });

async function state() {
  const response = await fetch(`${origin}/qa/state`);
  assert.equal(response.status, 200);
  return response.json();
}

async function noOverflow(page, label) {
  const sizes = await page.evaluate(() => ({
    viewport: innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  assert(sizes.document <= sizes.viewport + 1, `${label} document overflow ${JSON.stringify(sizes)}`);
  assert(sizes.body <= sizes.viewport + 1, `${label} body overflow ${JSON.stringify(sizes)}`);
}

async function screenshot(page, name) {
  if (shots) await page.screenshot({ path: `${shots}/${name}.png`, fullPage: true });
}

async function readableText(page, label) {
  const problems = await page.evaluate(() => {
    const values = [];
    const rgb = value => (value.match(/[\d.]+/g) || []).slice(0, 3).map(Number);
    const luminance = value => rgb(value).map(number => {
      const channel = number / 255;
      return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4;
    }).reduce((sum, channel, index) => sum + channel * [0.2126, 0.7152, 0.0722][index], 0);
    for (const element of document.querySelectorAll(".moderation-workspace *")) {
      if (!element.getClientRects().length || element.closest("[aria-hidden='true'],[hidden]") ||
          element.matches(":disabled") ||
          ![...element.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim())) continue;
      const style = getComputedStyle(element);
      const font = parseFloat(style.fontSize);
      if (font < 12) values.push(`${element.tagName}.${element.className}: ${font}px`);
      let parent = element;
      let background = "rgb(0, 0, 0)";
      while (parent) {
        const candidate = getComputedStyle(parent).backgroundColor;
        if (candidate && !candidate.endsWith(", 0)")) { background = candidate; break; }
        parent = parent.parentElement;
      }
      const ink = style.webkitTextFillColor && style.webkitTextFillColor !== "currentcolor"
        ? style.webkitTextFillColor : style.color;
      const lighter = Math.max(luminance(ink), luminance(background));
      const darker = Math.min(luminance(ink), luminance(background));
      const ratio = (lighter + 0.05) / (darker + 0.05);
      if (ratio < 4.5 && font < 19) values.push(`${element.tagName}: contrast ${ratio.toFixed(2)}`);
    }
    return values.slice(0, 12);
  });
  assert.deepEqual(problems, [], `${label} unreadable text: ${problems.join(", ")}`);
}

async function visit(browser, width, errors, writes) {
  const page = await browser.newPage({
    viewport: { width, height: width === 360 ? 800 : 1000 },
    reducedMotion: "reduce",
  });
  page.on("pageerror", error => errors.push(String(error)));
  page.on("request", request => {
    const url = new URL(request.url());
    if (url.origin !== origin && url.hostname !== "cdn.discordapp.com")
      errors.push(`Unexpected external request: ${request.url()}`);
    if (request.method() !== "GET") writes.push(`${request.method()} ${url.pathname}`);
  });
  await page.route("**/*", route => {
    const url = new URL(route.request().url());
    if (url.origin === origin) return route.continue();
    if (url.hostname === "cdn.discordapp.com")
      return route.fulfill({ contentType: "image/svg+xml", body: '<svg xmlns="http://www.w3.org/2000/svg"/>' });
    return route.abort();
  });
  await page.goto(`${origin}/server/moderation`);
  await page.getByRole("button", { name: "Open local test session" }).click();
  await page.locator(".moderation-workspace").waitFor();
  return page;
}

async function runWidth(browser, width, errors, writes) {
  const page = await visit(browser, width, errors, writes);
  try {
    const rows = page.locator(".member-activity-row");
    await rows.first().waitFor();
    assert.equal(await rows.count(), 4, `${width}: expected four saved history rows`);
    for (const name of ["Amber Archer", "Blaze Builder", "Cinder Captain", "Delta Defender"])
      assert.match(await page.locator(".member-activity").innerText(), new RegExp(name));
    await noOverflow(page, `${width} history`);
    await readableText(page, `${width} history`);
    await screenshot(page, `${width}-moderation-history`);

    await page.getByLabel("Search name or Discord ID").fill("Cinder");
    await page.getByRole("button", { name: "Apply filters" }).click();
    await page.waitForTimeout(100);
    assert.equal(await rows.count(), 1, `${width}: history search`);
    await page.getByLabel("Search name or Discord ID").fill("");
    await page.getByRole("button", { name: "Apply filters" }).click();
    await page.getByRole("navigation", { name: "Moderation sections" })
      .getByRole("button", { name: "Log settings" }).click();
    await page.getByRole("heading", { name: "Main log channel" }).waitFor();
    for (const event of ["Joins", "Leaves", "Kicks", "Bans"]) {
      const row = page.locator(".moderation-event-row").filter({ has: page.getByRole("switch", { name: `${event} logging` }) });
      await row.getByRole("button", { name: "Preview" }).click();
      await row.locator(".moderation-event-preview").waitFor();
      assert((await row.locator(".moderation-event-preview").innerText()).trim().length > 20,
        `${width}: ${event} preview is empty`);
      if (width === 360) {
        const previewWidth = await row.locator(".moderation-event-preview").evaluate(
          element => element.getBoundingClientRect().width,
        );
        assert(previewWidth >= 240, `${event} preview is only ${previewWidth}px wide on phone`);
      }
    }
    await noOverflow(page, `${width} settings`);
    await readableText(page, `${width} settings`);
    await screenshot(page, `${width}-moderation-settings`);

    const join = page.locator(".moderation-event-row").filter({ has: page.getByRole("switch", { name: "Joins logging" }) });
    await join.getByRole("button", { name: "Change" }).click();
    await join.getByRole("group", { name: "Joins destination mode" }).waitFor();
    if (width === 1440) {
      const override = join.getByRole("combobox", { name: "Joins channel override" });
      await override.fill("222222222222222222");
      await join.getByRole("option", { name: /Look up channel or forum post ID/ }).click();
      await join.getByText("Notices will be replies in this existing forum post.").waitFor();
    }
    await noOverflow(page, `${width} change`);
    await screenshot(page, `${width}-moderation-change`);
    await join.locator("label.moderation-event-pill").click();
    await page.getByRole("button", { name: "Discard", exact: true }).click();
    await page.getByRole("switch", { name: "Joins logging" }).waitFor();
    assert(await page.getByRole("switch", { name: "Joins logging" }).isChecked());

    const before = await state();
    const send = page.locator(".moderation-event-row").filter({ has: page.getByRole("switch", { name: "Joins logging" }) });
    await send.getByRole("button", { name: "Send test" }).click();
    const dialog = page.getByRole("dialog", { name: "Send test log" });
    await dialog.waitFor();
    await screenshot(page, `${width}-moderation-test-confirm`);
    await dialog.getByRole("button", { name: "Cancel" }).click();
    assert.equal((await state()).current.posts.length, before.current.posts.length,
      "Cancel posted a message");
    if (width === 1440) {
      await send.getByRole("button", { name: "Send test" }).click();
      await page.getByRole("dialog", { name: "Send test log" })
        .getByRole("button", { name: "Send one test" }).click();
      await page.getByText(/test log sent/i).waitFor();
      assert.equal((await state()).current.posts.length, before.current.posts.length + 1,
        "Confirmed test did not make exactly one fake Discord POST");
      await send.locator("label.moderation-event-pill").click();
      await page.getByRole("button", { name: "Save changes" }).click();
      await page.getByText("Moderation settings saved.").waitFor();
      assert.equal((await state()).current.settings_revision, 2);
      const conflict = await page.evaluate(async () => {
        const me = await (await fetch("/api/cwl/auth/me")).json();
        const saved = await (await fetch("/api/cwl/manage/member-events/settings")).json();
        const stale = Object.fromEntries(
          ["schema_version", "main", "categories", "events", "ignores"]
            .map(key => [key, saved[key]]),
        );
        const response = await fetch("/api/cwl/manage/member-events/settings", {
          method: "PUT", headers: { "Content-Type": "application/json", "X-CSRF-Token": me.csrf_token },
          body: JSON.stringify({ ...stale, revision: 1 }),
        });
        return response.status;
      });
      assert.equal(conflict, 409, "stale settings revision must conflict");
      assert.equal((await state()).current.settings_revision, 2);
      await fetch(`${origin}/qa/scenario?inventory_unavailable=1`);
      await page.getByRole("button", { name: "Reload settings" }).click();
      await page.getByText(/channel inventory is unavailable/i).first().waitFor();
      assert(await page.getByRole("combobox", { name: "Main log channel" }).isDisabled());
      await fetch(`${origin}/qa/scenario?inventory_unavailable=0&permission_denied=1`);
      await page.getByRole("button", { name: "Reload settings" }).click();
      await page.getByRole("alert").getByText(/permission|access|forbidden/i).waitFor();
      await fetch(`${origin}/qa/scenario?permission_denied=0`);
    }
  } finally {
    await page.close();
  }
}

(async () => {
  const errors = [];
  const writes = [];
  const baseline = (await state()).baseline;
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
  });
  try {
    for (const width of [360, 1440]) await runWidth(browser, width, errors, writes);
    const ending = (await state()).current;
    assert.equal(ending.history_count, baseline.history_count);
    assert.deepEqual(ending.history_ids, baseline.history_ids);
    assert.equal(ending.history_sha256, baseline.history_sha256);
    assert.equal(ending.posts.length, 1, "Only one explicit fake test should post");
    assert.equal(ending.posts[0].path, "/channels/1004519991648997447/messages");
    assert.equal(ending.audit_count, 2, "One confirmed send reserves and records one audit receipt");
    assert(writes.every(value => value === "POST /api/cwl/dev/login" ||
      value === "POST /api/cwl/manage/member-events/test" ||
      value === "PUT /api/cwl/manage/member-events/settings"), `Unexpected writes: ${writes}`);
    assert.deepEqual(errors, []);
    console.log("Moderation fixture: mobile and desktop history, previews, change, discard, cancel and one fake send passed");
  } finally {
    await browser.close();
  }
})().catch(error => { console.error(error); process.exitCode = 1; });
