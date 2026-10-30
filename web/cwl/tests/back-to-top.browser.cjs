const assert = require("node:assert/strict");

module.exports = async function checkBackToTop(page) {
  const button = page.getByRole("button", { name: "Back to top", exact: true });
  const reveal = async () => {
    await page.evaluate(() =>
      window.scrollTo({ top: 2800, behavior: "instant" }),
    );
    await page.waitForTimeout(120);
    await page.evaluate(() =>
      window.scrollTo({ top: 2600, behavior: "instant" }),
    );
    await button.waitFor({ state: "visible" });
  };
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  assert.equal(await button.count(), 0, "back-to-top visible at top");
  await reveal();
  let bounds = await button.boundingBox();
  assert(bounds.height >= 44, "back-to-top target below 44px");
  assert(
    Math.abs(bounds.x + bounds.width - 344) < 1,
    "right margin is not 16px",
  );
  assert(
    Math.abs(bounds.y + bounds.height - 784) < 1,
    "bottom margin is not 16px",
  );

  await page
    .locator('.roster-player-card input[type="checkbox"]')
    .first()
    .check();
  await reveal();
  bounds = await button.boundingBox();
  const dock = await page.locator(".roster-selection-dock").boundingBox();
  assert(
    bounds.y + bounds.height < dock.y,
    "back-to-top overlaps selection bar",
  );

  await page.evaluate(() =>
    window.scrollTo({
      top: document.documentElement.scrollHeight,
      behavior: "instant",
    }),
  );
  await page.waitForTimeout(120);
  await page.evaluate(() => window.scrollBy({ top: -50, behavior: "instant" }));
  await button.waitFor({ state: "visible" });
  const last = page.locator(".roster-player-card").last();
  const lastBounds = await last.boundingBox();
  bounds = await button.boundingBox();
  assert(
    lastBounds.y + lastBounds.height < bounds.y,
    "last card is covered by back-to-top",
  );
  const lastButton = last.locator("button").last();
  assert(await lastButton.isVisible(), "last card action is unavailable");
  assert(
    await lastButton.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return node.contains(
        document.elementFromPoint(
          rect.x + rect.width / 2,
          rect.y + rect.height / 2,
        ),
      );
    }),
    "last card action is obscured",
  );
  assert.equal(
    await page.evaluate(
      () => document.documentElement.scrollWidth > innerWidth,
    ),
    false,
  );
  await button.click();
  await page.waitForFunction(() => window.scrollY === 0);
  assert.equal(
    await page
      .locator("[data-roster-heading]")
      .evaluate((node) => node === document.activeElement),
    true,
  );
  await page
    .getByRole("button", { name: "Clear selected accounts", exact: true })
    .click();
};
