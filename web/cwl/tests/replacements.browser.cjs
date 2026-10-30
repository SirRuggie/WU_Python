const { chromium } = require("playwright");
const fs = require("node:fs"),
  assert = require("node:assert/strict");
const origin = "http://127.0.0.1:" + Number(process.argv[2]),
  out = process.env.WU_REPLACEMENTS_EVIDENCE;
if (out) fs.mkdirSync(out, { recursive: true });
(async () => {
  const b = await chromium.launch({
    executablePath: "/usr/bin/google-chrome",
    headless: true,
    args: ["--no-sandbox"],
  });
  const results = [];
  try {
    for (const width of [360, 1440]) {
      const p = await b.newPage({
          viewport: { width, height: width === 360 ? 800 : 1000 },
        }),
        errors = [];
      p.on("pageerror", (e) => errors.push(e.message));
      await p.route("**/*", (r) =>
        new URL(r.request().url()).origin === origin ? r.continue() : r.abort(),
      );
      const start = Date.now();
      await p.goto(origin + "/clans/replacements");
      await p.getByRole("button", { name: "Open local test session" }).click();
      await p.locator(".replacement-top li").first().waitFor();
      const elapsed = Date.now() - start;
      assert.equal(await p.locator(".replacement-row").count(), 0);
      assert.equal(await p.locator(".replacement-top li").count(), 10);
      const snap = async (name) => {
        assert.equal(
          await p.evaluate(() => document.documentElement.scrollWidth),
          width,
        );
        const violations = await p
          .locator(
            ".replacement-workspace, .strike-replacement-row, dialog[open]",
          )
          .evaluateAll((roots) =>
            roots.flatMap((root) =>
              [...root.querySelectorAll("button,input,select,textarea,a")]
                .filter((el) => el.checkVisibility() && !el.closest("[inert]"))
                .flatMap((el) => {
                  const target = el.matches("input[type=checkbox]")
                    ? el.closest("label")
                    : el;
                  const rect = target.getBoundingClientRect();
                  return rect.height < 44 ||
                    parseFloat(getComputedStyle(el).fontSize) < 12
                    ? [
                        {
                          text: el.textContent,
                          height: rect.height,
                          font: getComputedStyle(el).fontSize,
                        },
                      ]
                    : [];
                }),
            ),
          );
        assert.deepEqual(violations, [], name + " control targets and text");
        if (out) await p.screenshot({ path: `${out}/${width}-${name}.png` });
      };
      const first = await p.locator(".replacement-top h2").boundingBox();
      const recruit = await p.locator(".replacement-match h2").boundingBox();
      assert(first.y < 800 && recruit.y < 800);
      if (width === 1440) {
        assert(Math.abs(first.y - recruit.y) < 8, "Recruit box must sit beside Top 10");
        assert(first.x > recruit.x);
      }
      await snap("top");
      await p.getByLabel("Show 1–2 strikes too").check();
      await p
        .locator(".replacement-filters label")
        .filter({ hasText: /^Sort/ })
        .locator("select")
        .selectOption("weight");
      await p.getByLabel("Find account", { exact: true }).fill("Sample");
      await p
        .locator(".replacement-group-summary")
        .first()
        .scrollIntoViewIfNeeded();
      await snap("collapsed");
      await p.locator(".replacement-group-summary").first().click();
      await p.locator(".replacement-identity a").first().waitFor();
      await p
        .locator(".replacement-identity a")
        .first()
        .scrollIntoViewIfNeeded();
      await snap("open");
      const beforeScroll = await p.evaluate(() => scrollY);
      const href = await p
        .locator(".replacement-identity a")
        .first()
        .getAttribute("href");
      await p.locator(".replacement-identity a").first().click();
      await p.locator(".strikes-detail-context h2").waitFor();
      await p
        .getByRole("button", { name: "‹ Back to Replacements", exact: true })
        .waitFor();
      await snap("history");
      const row = p.locator(".strike-replacement-row");
      await row.getByRole("button", { name: "Edit", exact: true }).click();
      await row.locator("textarea").fill("Fixture draft");
      await snap("priority-editor");
      await row.getByRole("button", { name: "Cancel", exact: true }).click();
      await p
        .getByRole("button", { name: "Keep editing", exact: true })
        .click();
      assert.equal(await row.locator("textarea").inputValue(), "Fixture draft");
      await row.getByRole("button", { name: "Cancel", exact: true }).click();
      await snap("discard");
      await p.getByRole("button", { name: "Discard", exact: true }).click();
      await p
        .getByRole("button", { name: "‹ Back to Replacements", exact: true })
        .click();
      await p.locator(".replacement-identity a").first().waitFor();
      assert.equal(
        await p.getByLabel("Find account", { exact: true }).inputValue(),
        "Sample",
      );
      assert.equal(
        await p
          .locator(".replacement-filters label")
          .filter({ hasText: /^Sort/ })
          .locator("select")
          .inputValue(),
        "weight",
      );
      assert(await p.getByLabel("Show 1–2 strikes too").isChecked());
      await p.waitForFunction((y) => Math.abs(scrollY - y) < 100, beforeScroll);
      await snap("back");
      const clan = await p
        .locator(".replacement-group-summary[aria-expanded=true]")
        .first()
        .textContent();
      await p
        .getByRole("textbox", { name: "Recruit war weight", exact: true })
        .count()
        .then(async (n) => {
          const input = p.getByLabel("Recruit war weight", { exact: true });
          await input.fill("149");
        });
      await p.getByRole("button", { name: "Match", exact: true }).click();
      await p.waitForFunction(
        () => document.querySelectorAll(".replacement-row").length === 3,
      );
      const matchBox = await p.getByRole("button", {name:"Match", exact:true}).boundingBox();
      const resultBox = await p.locator(".replacement-match .replacement-row").first().boundingBox();
      assert(resultBox.y >= matchBox.y && resultBox.y - matchBox.y < 300, "Recruit results must be directly below Match");
      await snap("best-three");
      const state = await p.request
        .get(origin + "/qa/state")
        .then((r) => r.json());
      assert.equal(state.current.strike_hash, state.baseline.strike_hash);
      assert.equal(state.current.profiles, 273);
      assert.deepEqual(errors, []);
      results.push({
        width,
        firstLoadMs: elapsed,
        topCount: 10,
        closedInitial: true,
        roundTripFilters: true,
        roundTripScroll: true,
        historyHref: href,
        expandedClan: clan,
        bestSlots: 3,
        fixture: state,
      });
      await p.close();
    }
  } finally {
    await b.close();
  }
  if (out)
    fs.writeFileSync(out + "/layout.json", JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
