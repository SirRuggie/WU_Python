import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

const roster = readFileSync("src/StrikeActivityRoster.css", "utf8");
const block = (css: string, selector: string) => {
  const start = css.indexOf(`${selector} {`);
  expect(start, selector).toBeGreaterThanOrEqual(0);
  return css.slice(start, css.indexOf("}", start));
};

it("left-aligns slot results at every width", () => {
  const css = block(roster, ".strike-slot-group li > button");
  expect(css).toMatch(/justify-items:\s*start/);
  expect(css).toMatch(/justify-content:\s*stretch/);
  expect(css).toMatch(/text-align:\s*left/);
});

it("keeps slot results at full contrast even when not openable", () => {
  expect(roster).toMatch(
    /\.strike-slot-group li > button:disabled\s*\{[^}]*opacity:\s*1/,
  );
});

it("gives the Find slots controls two rows without truncating labels", () => {
  expect(block(roster, ".strike-find-slots-top")).toMatch(
    /grid-template-columns:\s*minmax\(0, 1fr\) auto/,
  );
  expect(block(roster, ".strike-find-slots-row")).toMatch(
    /grid-template-columns:\s*repeat\(2, minmax\(0, 1fr\)\)/,
  );
});

it("styles the Tracking status as a rounded chip", () => {
  expect(roster).toMatch(
    /\.strike-activity-status \.strikes-tracking > summary\s*\{[^}]*border-radius:\s*999px/,
  );
});
