/* Isolated staff_nav.py fixture only. No production requests or UI writes. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");

const port = Number(process.argv[2] || 8980);
assert(port >= 8900 && port <= 8999);
const base = `http://127.0.0.1:${port}`;
const evidence = process.env.WU_STAFF_NAV_EVIDENCE;
if (evidence) fs.mkdirSync(evidence, { recursive: true });

const expected = {
  member: {},
  limited: {
    "Staff overview": null,
    CWL: ["Build roster", "Declaration check"],
  },
  multi: {
    "Staff overview": null,
    CWL: ["Build roster", "Declaration check"],
    Moderation: null,
    Clans: ["Family clans", "Clan weights"],
    Members: ["Members & roles", "Tickets", "Ticket settings"],
    Bot: ["Command triggers", "Image gallery"],
  },
  owner: {
    "Staff overview": null,
    CWL: [
      "Seasons",
      "Signup reminders",
      "Build roster",
      "Finalize roster",
      "Announcements",
      "Declaration check",
      "Return reminders",
      "Results & participation",
      "Bonus medals",
      "Exports & history",
    ],
    Moderation: null,
    Clans: [
      "Family clans",
      "Clan weights",
      "Strikes & replacements",
      "FWA tools",
    ],
    Members: ["Members & roles", "Tickets", "Ticket settings"],
    Bot: ["Command triggers", "Image gallery", "Integrations"],
    Admin: ["Staff access", "Dashboard issues"],
  },
};

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH || "/usr/bin/google-chrome",
    args: ["--no-sandbox"],
  });
  const results = [];
  const errors = [];
  const writes = [];
  try {
    for (const role of ["member", "limited", "multi", "owner"]) {
      for (const [width, height] of [
        [360, 800],
        [1440, 1000],
      ]) {
        const context = await browser.newContext({
          viewport: { width, height },
        });
        await context.addInitScript(() => {
          localStorage.setItem(
            "wu-member-tour-v1",
            JSON.stringify({ skips: 3, dismissed: true }),
          );
        });
        const page = await context.newPage();
        page.on("pageerror", (error) => errors.push(String(error)));
        await page.route("**/*", (route) => {
          const request = route.request();
          const url = new URL(request.url());
          if (url.origin !== base) return route.abort();
          if (
            request.method() !== "GET" &&
            url.pathname !== "/api/cwl/dev/login"
          )
            writes.push(`${role}: ${request.method()} ${url.pathname}`);
          return route.continue();
        });
        try {
          const selected = await page.request.get(
            `${base}/qa/nav-role?role=${role}`,
          );
          assert.equal(selected.status(), 200);
          await page.goto(base + "/");
          await page
            .getByRole("button", { name: "Open local test session" })
            .click();
          await page
            .locator("#dashboard-navigation nav")
            .waitFor({ state: "attached" });
          const openMenu = async () => {
            if (
              width === 360 &&
              !(await page
                .locator(".sidebar")
                .evaluate((node) => node.classList.contains("open")))
            )
              await page.getByRole("button", { name: "Open menu" }).click();
          };
          await openMenu();
          const staff = page.locator(".navigation-staff");
          if (role === "member") {
            assert.equal(await staff.count(), 0);
          } else {
            assert.equal(await staff.count(), 1);
            assert.equal(
              await staff.locator(".navigation-staff-label").textContent(),
              "Staff tools",
            );
            assert.equal(
              await staff.locator(".navigation-staff-label button").count(),
              0,
            );
            const sectionNames = await staff
              .locator(":scope > .navigation-section")
              .evaluateAll((sections) =>
                sections.map((section) =>
                  section.querySelector(":scope > button")?.textContent.trim(),
                ),
              );
            assert.deepEqual(sectionNames, Object.keys(expected[role]));
            assert.equal(
              await staff
                .locator(".navigation-children .navigation-section")
                .count(),
              0,
              "Staff groups must stay flat",
            );
            for (const [index, [group, items]] of Object.entries(
              expected[role],
            ).entries()) {
              const section = staff
                .locator(":scope > .navigation-section")
                .nth(index);
              if (items === null) {
                assert.equal(
                  await section.locator(".navigation-toggle").count(),
                  0,
                );
                continue;
              }
              const toggle = section.locator(":scope > .navigation-toggle");
              assert.equal(await toggle.getAttribute("aria-expanded"), "false");
              await toggle.click();
              assert.equal(await toggle.getAttribute("aria-expanded"), "true");
              assert.deepEqual(
                await section
                  .locator(".navigation-children > button")
                  .allTextContents(),
                items,
                `${role}: ${group} item order`,
              );
              await toggle.click();
            }
            for (const section of await staff
              .locator(":scope > .navigation-section")
              .all()) {
              const toggle = section.locator(":scope > .navigation-toggle");
              if (await toggle.count()) await toggle.click();
            }
          }
          assert.equal(
            (await page.locator(".navigation-section").count()) >= 3,
            true,
          );
          const layout = await page.evaluate(() => {
            const sidebar = document.querySelector(".sidebar");
            const nav = sidebar.querySelector("nav");
            const footer = sidebar.querySelector(".sidebar-foot");
            const sidebarRect = sidebar.getBoundingClientRect();
            const footerRect = footer.getBoundingClientRect();
            return {
              pageOverflow: document.documentElement.scrollWidth > innerWidth,
              sidebarOverflow: sidebar.scrollWidth > sidebar.clientWidth,
              navScrollable: nav.scrollHeight > nav.clientHeight,
              footerTop: footerRect.top,
              footerBottom: footerRect.bottom,
              sidebarBottom: sidebarRect.bottom,
              buttons: [...nav.querySelectorAll("button")]
                .filter((button) => button.getClientRects().length)
                .map((button) => ({
                  label: button.textContent.trim(),
                  height: button.getBoundingClientRect().height,
                  overflow: button.scrollWidth > button.clientWidth,
                })),
            };
          });
          assert.equal(
            layout.pageOverflow,
            false,
            `${role} ${width}: page overflow`,
          );
          assert.equal(
            layout.sidebarOverflow,
            false,
            `${role} ${width}: sidebar overflow`,
          );
          assert(
            layout.buttons.every(
              ({ height, overflow }) => height >= 44 && !overflow,
            ),
            `${role} ${width}: short or clipped menu target ${JSON.stringify(layout.buttons)}`,
          );
          assert(layout.footerTop >= 0 && layout.footerBottom <= height + 1);
          assert(Math.abs(layout.footerBottom - layout.sidebarBottom) <= 1);
          if (role === "owner")
            assert(layout.navScrollable, "Owner directory should scroll");
          if (evidence && (width === 360 || role === "owner")) {
            await page.locator("#dashboard-navigation nav").evaluate((nav) => {
              nav.scrollTop = 0;
            });
            await page.screenshot({
              path: `${evidence}/${role}-${width}.png`,
              fullPage: false,
            });
          }
          if (role === "limited") {
            const cwl = staff.locator(":scope > .navigation-section").nth(1);
            await cwl.getByRole("button", { name: "Build roster" }).click();
            await openMenu();
            await page
              .getByRole("button", { name: "Build roster", exact: true })
              .waitFor();
            assert.equal(new URL(page.url()).pathname, "/cwl/roster");
            assert.equal(
              await cwl
                .locator(":scope > .navigation-toggle")
                .getAttribute("aria-expanded"),
              "true",
            );
            await page.reload();
            await page
              .locator("#dashboard-navigation nav")
              .waitFor({ state: "attached" });
            await openMenu();
            assert.equal(
              await cwl
                .locator(":scope > .navigation-toggle")
                .getAttribute("aria-expanded"),
              "true",
              "Current group opens on remount",
            );
            await cwl.locator(":scope > .navigation-toggle").click();
            await staff.getByRole("button", { name: "Staff overview" }).click();
            await page.reload();
            await page
              .locator("#dashboard-navigation nav")
              .waitFor({ state: "attached" });
            await openMenu();
            assert.equal(new URL(page.url()).pathname, "/staff");
            assert.equal(
              await cwl
                .locator(":scope > .navigation-toggle")
                .getAttribute("aria-expanded"),
              "false",
              "Collapsed group stays closed on another page",
            );
            await cwl.locator(":scope > .navigation-toggle").click();
            await cwl.getByRole("button", { name: "Build roster" }).click();
            await openMenu();
            assert.equal(
              await cwl
                .locator(":scope > .navigation-toggle")
                .getAttribute("aria-expanded"),
              "true",
              "Navigating back opens the current group",
            );
          }
          if (role === "multi") {
            await staff.getByRole("button", { name: "Moderation" }).click();
            await openMenu();
            assert.equal(new URL(page.url()).pathname, "/server/moderation");
            assert.equal(
              await page.locator(".topbar strong").textContent(),
              "Moderation",
            );
          }
          results.push({ role, width, ...layout });
        } finally {
          await context.close();
        }
      }
    }
    assert.deepEqual(writes, []);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ results, writes, errors }, null, 2));
  } finally {
    await browser.close();
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
