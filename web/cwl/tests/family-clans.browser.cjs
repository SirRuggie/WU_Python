const { chromium } = require("playwright"),
  fs = require("node:fs"),
  assert = require("node:assert/strict");
const origin = "http://127.0.0.1:" + Number(process.argv[2]),
  out = process.env.WU_FAMILY_EVIDENCE || "/tmp/wu-family-layout";
fs.mkdirSync(out, { recursive: true });
(async () => {
  const b = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const evidence = [];
  try {
    for (const width of [320, 360, 390, 1440]) {
      const p = await b.newPage({
          viewport: { width, height: width <= 800 ? 800 : 1000 },
        }),
        errors = [],
        writes = [];
      p.on("pageerror", (e) => errors.push(e.message));
      p.on("request", (r) => {
        if (
          r.method() !== "GET" &&
          r.url().includes("/manage/") &&
          !r.url().endsWith("/preview")
        )
          writes.push(r.url());
      });
      await p.route("**/*", (r) =>
        new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
      );
      const snap = async (name) => {
        const m = await p.locator(".clan-management").evaluate((root) => ({
          width: document.documentElement.scrollWidth,
          height: root.getBoundingClientRect().height,
          controls: [
            ...document.querySelectorAll(
              ".clan-management button,.clan-management input,.clan-management select,.clan-management textarea,.clan-management a,dialog[open] button",
            ),
          ]
            .filter((el) => el.checkVisibility() && !el.closest("[inert]"))
            .flatMap((el) => {
              const target = el.matches('input[type="checkbox"]')
                ? el.closest("label") || el
                : el;
              const r = target.getBoundingClientRect(),
                font = parseFloat(getComputedStyle(el).fontSize);
              return r.height < 44 || font < 12
                ? [{ text: el.textContent, height: r.height, font }]
                : [];
            }),
        }));
        evidence.push({ width, name, ...m });
        await p.screenshot({
          path: `${out}/${width}-${name}.png`,
          fullPage: true,
        });
        assert.equal(m.width, width, name + " overflow");
        assert.deepEqual(m.controls, [], name + " targets");
      };
      await p.goto(origin + "/clans");
      await p.getByRole("button", { name: "Open local test session" }).click();
      await p.locator(".clan-directory button").first().waitFor();
      await snap("directory");
      await p.locator(".clan-directory button").first().click();
      await p.getByRole("navigation", { name: "Used by" }).waitFor();
      await snap("clan");
      await p.goBack();
      await p.locator(".clan-editor").waitFor({ state: "hidden" });
      await p.goForward();
      await p.locator(".clan-editor").waitFor();
      await p.getByLabel("Clan name", { exact: true }).fill("Edited example");
      await snap("unsaved");
      await p.goBack();
      await p.locator("dialog[open]").waitFor();
      await p.getByRole("button", { name: "Cancel", exact: true }).click();
      assert(
        (await p.getByLabel("Clan name", { exact: true }).inputValue()) ===
          "Edited example",
      );
      await p.getByRole("button", { name: "Discard", exact: true }).click();
      if (await p.locator("dialog[open]").count())
        await p.locator("dialog[open] .primary").click();
      await p.getByRole("button", { name: "Remove clan", exact: true }).click();
      await snap("remove-confirm");
      await p.getByRole("button", { name: "Cancel", exact: true }).click();
      if (width <= 800) await p.locator('.clan-section-toggle').filter({hasText:'War reminders'}).click();
      else await p.getByRole('tab', {name:'War reminders', exact:true}).click();
      await p.getByText("Preview & send a test", { exact: true }).click();
      await p
        .getByText("Sample war reminder · 1h left", { exact: true })
        .waitFor();
      await p
        .getByRole("button", {
          name: "Send test to selected channel",
          exact: true,
        })
        .click();
      await snap("test-confirm");
      await p.getByRole("button", { name: "Cancel", exact: true }).click();
      await p.getByRole("button", { name: "Reminders", exact: true }).click();
      await p.locator(".reminder-overview").waitFor();
      await snap("reminders");
      await p.getByRole("button", { name: "History", exact: true }).click();
      await p.getByText("Leader role: Old leaders → Clan leaders").waitFor();
      await snap("history");
      await p.goto(origin + "/clans");
      await p.locator(".clan-directory button").first().click();
      await p.locator(".clan-editor").waitFor();
      await p.getByRole("button", { name: "+ Add clan", exact: true }).click();
      await p.locator(".clan-editor").waitFor({ state: "hidden" });
      assert.equal(new URL(p.url()).pathname, "/clans");
      await snap("add-after-editor");
      assert.deepEqual(errors, []);
      assert.deepEqual(writes, []);
      await p.close();
    }
  } finally {
    fs.writeFileSync(out + "/metrics.json", JSON.stringify(evidence, null, 2));
    await b.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
