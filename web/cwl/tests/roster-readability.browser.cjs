/*
 * Isolated visual/interaction checks for the Accounts & signups readability work.
 * Start fixtures/roster_readability.py on a loopback port (default 8982), then:
 *   node tests/roster-readability.browser.cjs 8982
 * Optional screenshots go to WU_LAYOUT_SCREENSHOTS. The only UI write is the
 * fixture's local dev-login; state changes use its QA-only publication switch.
 */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");

const port = Number(process.argv[2] || 8982);
assert(Number.isInteger(port) && port >= 8900 && port <= 8999);
const origin = `http://127.0.0.1:${port}`;
const screenshotDir = process.env.WU_LAYOUT_SCREENSHOTS;
const errors = [];
const expectedResponses = [];
const passes = [];

async function fixtureState() {
  const response = await fetch(`${origin}/qa/state`);
  assert.equal(response.status, 200);
  return response.json();
}

async function setPublicationState(state) {
  const response = await fetch(`${origin}/qa/publication-state`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ state }),
  });
  assert.equal(response.status, 200, `fixture could not set ${state}`);
  return response.json();
}

async function openRoster(browser, width, height) {
  const page = await browser.newPage({ viewport: { width, height } });
  page.on("pageerror", (error) => errors.push(String(error)));
  page.on("console", (message) => {
    if (
      message.type() === "error" &&
      !message.text().startsWith("Failed to load resource")
    )
      errors.push(message.text());
  });
  page.on("response", (response) => {
    if (response.status() < 400) return;
    const path = new URL(response.url()).pathname;
    if (response.status() === 401 && path === "/api/cwl/auth/me") {
      expectedResponses.push(
        `HTTP 401 ${path} (fresh unauthenticated session probe)`,
      );
    } else if (response.status() === 404 && path === "/api/cwl/prank/state") {
      expectedResponses.push(
        `HTTP 404 ${path} (owner-only prank is disabled in the fixture)`,
      );
    } else {
      errors.push(`HTTP ${response.status()} ${response.url()}`);
    }
  });
  page.on("requestfailed", (request) => {
    errors.push(
      `Request failed ${request.url()} (${request.failure()?.errorText || "unknown"})`,
    );
  });
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (url.hostname !== "cdn.discordapp.com" && url.origin !== origin)
      errors.push(`External request attempted: ${request.url()}`);
  });
  await page.route("**/*", (route) => {
    const url = new URL(route.request().url());
    if (url.hostname === "cdn.discordapp.com") {
      return route.fulfill({
        contentType: "image/svg+xml",
        body: '<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect width="64" height="64" fill="#f0d080"/><path d="M0 0L64 64M64 0L0 64" stroke="#181818" stroke-width="4"/></svg>',
      });
    }
    return url.origin === origin ? route.continue() : route.abort();
  });
  await page.goto(`${origin}/cwl/roster?season=1`);
  await page.getByRole("button", { name: "Open local test session" }).click();
  await page.locator(".roster-player-card").first().waitFor();
  return page;
}

function rgb(value) {
  const parts = value.match(/[\d.]+/g)?.map(Number) || [];
  return parts.length >= 3 ? parts.slice(0, 3) : null;
}

function luminance(color) {
  const linear = color.map((channel) => {
    const value = channel / 255;
    return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

async function checkFades(page, selector) {
  const strip = page.locator(selector).first();
  await strip.waitFor();
  const measure = () =>
    strip.evaluate((node) => {
      const style = getComputedStyle(node);
      const before = getComputedStyle(node, "::before");
      const after = getComputedStyle(node, "::after");
      return {
        overflow: node.scrollWidth > node.clientWidth + 1,
        atStart: node.scrollLeft <= 1,
        atEnd: node.scrollLeft + node.clientWidth >= node.scrollWidth - 1,
        fadeLeft: node.dataset.fadeLeft === "true",
        fadeRight: node.dataset.fadeRight === "true",
        mask: style.maskImage || style.webkitMaskImage,
        before: before.backgroundImage,
        after: after.backgroundImage,
      };
    });
  const initial = await measure();
  if (!initial.overflow) {
    assert.equal(
      initial.fadeLeft,
      false,
      `${selector}: left fade shown without overflow`,
    );
    assert.equal(
      initial.fadeRight,
      false,
      `${selector}: right fade shown without overflow`,
    );
    assert(
      !initial.mask || initial.mask === "none",
      `${selector}: mask shown without overflow`,
    );
    passes.push(`${selector}: no overflow, no fades`);
    return;
  }
  assert.equal(
    initial.fadeRight,
    true,
    `${selector}: right overflow fade missing`,
  );
  assert.equal(
    initial.fadeLeft,
    false,
    `${selector}: left fade shown at start`,
  );
  assert(
    /gradient/i.test(initial.mask || ""),
    `${selector}: fade mask missing`,
  );
  await strip.evaluate((node) => {
    node.scrollLeft = node.scrollWidth;
  });
  await page.waitForFunction((selector) => {
    const node = document.querySelector(selector);
    return (
      node?.dataset.fadeLeft === "true" && node.dataset.fadeRight === "false"
    );
  }, selector);
  const end = await measure();
  assert.equal(
    end.fadeLeft,
    true,
    `${selector}: left overflow fade missing at end`,
  );
  assert.equal(end.fadeRight, false, `${selector}: right fade shown at end`);
  passes.push(`${selector}: overflow fades track both edges`);
  await strip.evaluate((node) => {
    node.scrollLeft = 0;
  });
}

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  let phone;
  try {
    await setPublicationState("hidden");
    const initial = await fixtureState();
    const countsBefore = initial.current;
    assert.equal(countsBefore.account_count, 125);
    assert.equal(countsBefore.unreviewed_changes, 1);
    assert(
      countsBefore.manual_weights.some((row) => row.manual_weight == null),
    );
    assert(
      countsBefore.manual_weights.some((row) => row.manual_weight != null),
    );
    assert(
      countsBefore.rules.some(
        (row) =>
          row.tag === "#U2Y" && row.pool === "main" && row.capacity == null,
      ),
    );

    phone = await openRoster(browser, 360, 800);
    assert.equal(
      await phone.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
      "phone page overflows horizontally",
    );
    assert(
      await phone
        .locator(".roster-player-body > .player-card-top:visible")
        .count(),
      "phone card top is missing",
    );
    assert(
      await phone
        .locator(".roster-player-body > .player-card-meta:visible")
        .count(),
      "phone card metadata is missing",
    );
    assert(
      await phone
        .locator(".roster-player-body > .player-clan-status:visible")
        .count(),
      "phone clan status is missing",
    );
    assert(
      await phone
        .locator(".roster-account-columns")
        .evaluateAll((nodes) =>
          nodes.every((node) => getComputedStyle(node).display === "none"),
        ),
      "desktop columns were applied on phone",
    );
    if (screenshotDir)
      await phone.screenshot({
        path: `${screenshotDir}/phone-top-hidden.png`,
        fullPage: false,
      });

    const publication = phone.locator(".publication-awareness");
    await publication.waitFor();
    const statusLine = async (state, expected, screenshot) => {
      await setPublicationState(state);
      await phone.reload();
      await phone.locator(".roster-player-card").first().waitFor();
      const line = phone.locator(".publication-awareness");
      await line.waitFor();
      await phone.getByText(expected).waitFor({ state: "visible" });
      const text = (await line.innerText()).replace(/\s+/g, " ");
      assert.match(text, expected, `${state} publication status`);
      if (screenshotDir)
        await phone.screenshot({
          path: `${screenshotDir}/${screenshot}`,
          fullPage: false,
        });
      return text;
    };
    const hiddenText = await statusLine(
      "hidden",
      /Hidden from members.*v1.*Oct 15/i,
      "status-hidden.png",
    );
    const draftText = await statusLine(
      "draft",
      /Draft.*not published/i,
      "status-draft.png",
    );
    const publishedText = await statusLine(
      "published",
      /Published.*v3.*Oct 28.*Members can see it/i,
      "status-published.png",
    );
    assert(
      !/Draft · not published/i.test(hiddenText),
      "hidden state has duplicate draft label",
    );
    assert(
      !/Draft · not published/i.test(publishedText),
      "published state has duplicate draft label",
    );

    await setPublicationState("hidden");
    await phone.reload();
    await phone.locator(".roster-player-card").first().waitFor();
    await checkFades(phone, ".roster-header-working");
    await checkFades(phone, ".roster-workflow-nav");

    const activityLine = phone.locator(".signup-activity-line").first();
    await activityLine.waitFor();
    const activityText = await activityLine.innerText();
    assert.match(activityText, /1 signup change to review/i);
    const alertOrder = await phone.evaluate(() => {
      const status = document.querySelector(".publication-awareness");
      const activity = document.querySelector(".signup-activity-line");
      const shortage = [
        ...document.querySelectorAll("button,a,[role=button]"),
      ].find((node) =>
        /players.*more|players\s*›/i.test(node.textContent || ""),
      );
      return {
        status: status?.getBoundingClientRect().top,
        activity: activity?.getBoundingClientRect().top,
        shortage: shortage?.getBoundingClientRect().top,
      };
    });
    assert(
      alertOrder.status < alertOrder.activity,
      "signup-change alert must follow publication status",
    );
    assert(
      alertOrder.shortage == null || alertOrder.activity < alertOrder.shortage,
      "shortage must follow signup-change alert",
    );
    await activityLine.click();
    await phone.locator(".signup-activity-panel").waitFor();
    assert.equal(
      await phone.locator(".signup-activity-review").count(),
      1,
      "expected one review action; do not invoke it",
    );
    await phone
      .getByRole("button", { name: "Close panel", exact: true })
      .click();
    const phoneList = phone.locator(".roster-account-list");
    await phoneList.waitFor();
    const firstLocatedCard = phone
      .locator(".roster-player-card")
      .filter({
        has: phone.locator(
          ".roster-player-body > .player-clan-status .player-location-pin",
        ),
      })
      .first();
    await firstLocatedCard.waitFor();
    assert(
      (await firstLocatedCard
        .getByRole("note", { name: /Now in .+/ })
        .count()) > 0,
      "current clan has no accessible Now in description",
    );
    passes.push("current clan has an accessible Now in name");
    await firstLocatedCard.scrollIntoViewIfNeeded();
    if (screenshotDir)
      await phone.screenshot({
        path: `${screenshotDir}/phone-cards.png`,
        fullPage: false,
      });

    const missingCapacity = phone
      .locator(".roster-capacity-alert")
      .filter({ hasText: "Funnies" })
      .getByRole("button", { name: "Set in Hosting clans" });
    await missingCapacity.waitFor();
    assert.equal(
      await phone.getByText(/has no capacity set/i).count(),
      1,
      "capacity warning should appear once above the cards",
    );
    assert.equal(
      await phone
        .locator(".roster-player-card")
        .filter({ hasText: /no capacity set/i })
        .count(),
      0,
      "capacity warning remains duplicated in a player card",
    );
    const linkBox = await missingCapacity.boundingBox();
    assert(
      linkBox && linkBox.height >= 44,
      "capacity action target is under 44px",
    );
    await missingCapacity.click();
    await phone
      .getByRole("button", { name: "Hosting clans", exact: true })
      .waitFor();
    const selectedClan = phone.locator(".clan-settings-row.is-selected");
    await selectedClan.waitFor();
    assert.match(await selectedClan.innerText(), /Funnies/);
    await phone
      .getByRole("button", { name: "Accounts & signups", exact: true })
      .click();
    await phone.locator(".roster-player-card").first().waitFor();
    const settingsTab = phone.getByRole("button", {
      name: "Hosting clans",
      exact: true,
    });
    await settingsTab.click();
    await phone.locator(".clan-settings-row").first().waitFor();
    assert.equal(
      await phone.locator(".clan-settings-row.is-selected").count(),
      0,
      "capacity focus request replayed when returning to the tab",
    );
    assert(
      await settingsTab.evaluate((node) => document.activeElement === node),
      "returning to Hosting clans moved focus into the list",
    );
    passes.push("capacity focus consumed once; tab return preserves focus");
    await phone.getByRole("button", { name: /Missing weights/ }).click();
    await phone.locator(".publication-awareness").waitFor();
    assert.match(
      await phone.locator(".publication-awareness").innerText(),
      /Hidden from members/,
    );
    passes.push("Missing weights retains the slim publication state");

    const amberLine = phone.locator(".signup-activity-line").first();
    const amber = await amberLine.evaluate((node) => {
      const style = getComputedStyle(node);
      let parent = node;
      while (
        parent &&
        getComputedStyle(parent).backgroundColor === "rgba(0, 0, 0, 0)"
      )
        parent = parent.parentElement;
      return {
        fontSize: parseFloat(style.fontSize),
        foreground: style.color,
        background: parent
          ? getComputedStyle(parent).backgroundColor
          : "rgb(255,255,255)",
        height: node.getBoundingClientRect().height,
      };
    });
    assert(amber.fontSize >= 12, "amber summary text is below 12px");
    assert(amber.height >= 44, "amber summary action target is below 44px");
    const fg = rgb(amber.foreground),
      bg = rgb(amber.background);
    let contrastRatio = null;
    if (fg && bg) {
      const a = luminance(fg),
        b = luminance(bg);
      contrastRatio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      assert(contrastRatio >= 4.5, "amber line contrast is below 4.5:1");
    }

    passes.push("amber alert: >=44px target, >=12px text, >=4.5 contrast");
    await phone
      .getByRole("button", { name: "Accounts & signups", exact: true })
      .click();
    await phone.locator(".roster-player-card").first().waitFor();
    const seasonRow = await phone
      .locator(".roster-header-publication")
      .evaluate((node) => {
        const button = node.querySelector("button");
        const r = button.getBoundingClientRect();
        return {
          width: r.width,
          height: r.height,
          left: r.left,
          right: r.right,
          standaloneFinalizeCount: document.querySelectorAll(
            ".roster-header-finalize",
          ).length,
        };
      });
    assert(
      seasonRow.width < 160 && seasonRow.right <= 360,
      "phone season control stretched",
    );
    await phone.evaluate(() =>
      window.scrollTo({ top: 0, behavior: "instant" }),
    );
    if (screenshotDir)
      await phone.screenshot({
        path: `${screenshotDir}/phone-season-row.png`,
        fullPage: false,
      });
    passes.push(
      "phone season control remains compact after Draft field removal",
    );
    await phone
      .getByRole("button", { name: "Compare clans", exact: true })
      .click();
    await phone
      .getByRole("note", { name: /Now in .+/ })
      .first()
      .waitFor();
    const cdp = await phone.context().newCDPSession(phone);
    const { nodes: accessibilityNodes } = await cdp.send(
      "Accessibility.getFullAXTree",
    );
    const describedCards = accessibilityNodes.filter(
      (node) =>
        node.role?.value === "button" &&
        /Details for/.test(node.name?.value || "") &&
        /Now in/.test(node.description?.value || ""),
    );
    assert(
      describedCards.length > 0,
      "Compare Details has no computed location description",
    );
    for (const node of describedCards)
      assert.equal((node.description.value.match(/Now in/g) || []).length, 1);
    const locationNotes = accessibilityNodes.filter(
      (node) =>
        node.role?.value === "note" && /Now in/.test(node.name?.value || ""),
    );
    assert(locationNotes.length > 0, "Chrome exposes no location notes");
    assert(
      locationNotes.every((node) => node.childIds.length === 0),
      "Location notes contain duplicate spoken text children",
    );
    const accessibleDescription = describedCards[0].description.value;
    await cdp.detach();
    passes.push(
      "Chrome AX: Compare location described once; named notes have no duplicate text children",
    );
    const desktop = await openRoster(browser, 1440, 1000);
    assert.equal(
      await desktop.evaluate(
        () => document.documentElement.scrollWidth > innerWidth,
      ),
      false,
      "desktop page overflows horizontally",
    );
    await checkFades(desktop, ".roster-header-working");
    await checkFades(desktop, ".roster-workflow-nav");
    const columns = desktop.locator(".roster-account-columns").first();
    await columns.waitFor();
    const visibleColumns = await columns.evaluate(
      (node) => getComputedStyle(node).display !== "none",
    );
    assert(visibleColumns, "desktop account columns are hidden");
    assert.equal(
      await desktop
        .locator(
          ".roster-player-body > .player-card-top:visible, .roster-player-body > .player-card-meta:visible, .roster-player-body > .player-clan-status:visible",
        )
        .count(),
      0,
      "phone card layout remains visible on desktop",
    );
    const aligned = await desktop
      .locator(".roster-account-columns")
      .evaluateAll((nodes) => {
        const fields = ["name", "pool", "assigned", "now", "weight"];
        const rows = nodes.slice(0, 2).map((row) =>
          fields.map((field) => {
            const cell = row.querySelector(`.roster-account-column-${field}`);
            return cell ? Math.round(cell.getBoundingClientRect().left) : null;
          }),
        );
        return { rows, firstText: nodes[0]?.innerText || "" };
      });
    assert(aligned.rows.length >= 2, "expected two desktop account rows");
    for (let index = 0; index < 5; index++)
      assert.equal(
        aligned.rows[0][index],
        aligned.rows[1][index],
        `desktop column ${index} is not aligned`,
      );
    await desktop
      .getByPlaceholder("Name, player tag or Discord ID")
      .fill("FifteenCharName");
    await desktop.waitForFunction(() =>
      [...document.querySelectorAll(".roster-account-column-name")].some(
        (node) => node.textContent.includes("FifteenCharName"),
      ),
    );
    const longNameRow = desktop
      .locator(".roster-player-card:visible")
      .filter({ hasText: "FifteenCharName" })
      .first();
    assert.match(
      await longNameRow.locator(".roster-account-column-name").innerText(),
      /FifteenCharName/,
    );
    assert.match(
      await longNameRow.locator(".roster-account-column-assigned").innerText(),
      /Warriors Unite!/,
    );
    await desktop
      .locator(".roster-player-card:visible")
      .first()
      .evaluate((node) =>
        window.scrollTo(
          0,
          node.getBoundingClientRect().top + window.scrollY - 240,
        ),
      );
    if (screenshotDir)
      await desktop.screenshot({
        path: `${screenshotDir}/desktop-columns.png`,
        fullPage: false,
      });

    passes.push("1440px account columns align; phone columns stay hidden");
    await desktop.close();
    const after = await fixtureState();
    assert.equal(after.current.account_count, countsBefore.account_count);
    assert.equal(
      after.current.unreviewed_changes,
      countsBefore.unreviewed_changes,
    );
    assert.deepEqual(
      after.current.season_counts,
      countsBefore.season_counts,
      "season counts changed during read-only UI checks",
    );
    assert.deepEqual(
      after.current.reviews,
      countsBefore.reviews,
      "signup review records changed during UI checks",
    );
    assert.deepEqual(
      after.current.manual_weights,
      countsBefore.manual_weights,
      "manual weights changed during UI checks",
    );
    assert.deepEqual(
      after.current.saved_weights,
      countsBefore.saved_weights,
      "saved weights changed during UI checks",
    );
    assert.deepEqual(
      after.current.rules,
      countsBefore.rules,
      "clan rules changed during UI checks",
    );
    assert.deepEqual(
      after.current.publications,
      countsBefore.publications,
      "publication state not restored",
    );
    const writes = after.requests.filter(
      (request) =>
        request.method !== "GET" && request.path !== "/api/cwl/dev/login",
    );
    assert.deepEqual(writes, [], "browser invoked a non-login API write");
    assert.deepEqual(
      errors,
      [],
      `browser errors or blocked external requests: ${errors.join("; ")}`,
    );
    console.log(
      JSON.stringify(
        {
          ok: true,
          passCount: passes.length,
          passes,
          seasonRow,
          accessibleDescription,
          widthChecks: [360, 1440],
          statusStates: [draftText, hiddenText, publishedText],
          seasonCountsBeforeAfter: {
            before: countsBefore.season_counts,
            after: after.current.season_counts,
          },
          amberMetrics: {
            fontSizePx: amber.fontSize,
            targetHeightPx: amber.height,
            contrastRatio,
          },
          expectedResponses,
          screenshots: screenshotDir || null,
          writes,
        },
        null,
        2,
      ),
    );
  } finally {
    await phone?.close();
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
