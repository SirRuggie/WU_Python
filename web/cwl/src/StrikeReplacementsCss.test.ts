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
it("clips duplicate settled announcements without removing them from accessibility", () => {
  const hidden = block(roster, ".strike-slot-live.sr-only");
  expect(hidden).toMatch(/position:\s*absolute/);
  expect(hidden).toMatch(/width:\s*1px/);
  expect(hidden).toMatch(/height:\s*1px/);
  expect(hidden).toMatch(/clip-path:\s*inset\(50%\)/);
  expect(hidden).not.toMatch(/display:\s*none|visibility:\s*hidden/);
  expect(roster).toMatch(/\.strike-slot-live\.sr-only\s*\{\s*min-height:\s*0/);
});

it("keeps slot results at full contrast even when not openable", () => {
  expect(roster).toMatch(
    /\.strike-slot-group li > button:disabled\s*\{[^}]*opacity:\s*1/,
  );
});

it("lays out inline filters in four columns and stacks them on phones", () => {
  expect(block(roster, ".strike-slot-filters")).toMatch(
    /grid-template-columns:\s*minmax\(160px, 1fr\) minmax\(150px, 1fr\) minmax\(190px, 1\.2fr\)\s*minmax\(110px, 0\.6fr\)/,
  );
  const phone = roster.slice(roster.indexOf("@media (max-width: 760px)"));
  expect(block(phone, ".strike-slot-filters")).toMatch(
    /grid-template-columns:\s*minmax\(0, 1fr\)/,
  );
  expect(block(phone, ".strike-slot-results")).toMatch(/max-height:\s*55dvh/);
});

it("styles the Tracking status as a gold text link, not a bordered chip", () => {
  const summary = block(
    roster,
    ".strike-activity-status .strikes-tracking > summary",
  );
  expect(summary).toMatch(/border:\s*0/);
  expect(summary).not.toMatch(/border-radius:\s*999px/);
  expect(summary).toMatch(/color:\s*var\(--wu-text-muted\)/);
  expect(
    block(roster, ".strike-activity-status .strikes-tracking > summary.review"),
  ).toMatch(/color:\s*var\(--wu-accent\)/);
});

it("gives the native selects an explicit background and text colour from tokens", () => {
  const css = block(
    roster,
    ".strike-activity-view-select,\n.strike-activity-selectors select",
  );
  expect(css).toMatch(/background-color:\s*var\(--wu-surface\)/);
  expect(css).toMatch(/color:\s*var\(--wu-text\)/);
});
