import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { steps } from "./memberTour/model";

it("retains the exact approved tour greeting", () => {
  expect(steps[0].title).toBe("Hey Chief, welcome to Warriors United!");
});

it("provides reduced-motion overrides for all three actual menu overlays", () => {
  for (const file of [
    "rosterUi/ActionMenu.css",
    "AccountMenu.css",
    "rosterUi/SortTrigger.css",
  ]) {
    const css = readFileSync(`src/${file}`, "utf8");
    expect(css).toMatch(/wu-popover-enter 150ms/);
    expect(css).toMatch(/wu-popover-exit 100ms/);
    expect(css).toMatch(
      /@media\s*\(prefers-reduced-motion:\s*reduce\)\s*\{[\s\S]*animation:\s*none\s*!important/,
    );
  }
});

it("limits the tap demonstration and removes decorative/reduced-motion tour animation", () => {
  const css = readFileSync("src/memberTour/tour.css", "utf8");
  expect(css).toMatch(/tour-tap 1\.6s 3/);
  expect(css).toMatch(/tour-ripple 1\.6s 3/);
  expect(css).not.toContain("infinite");
  expect(css).not.toContain("tour-fall");
  expect(css).not.toContain("tour-pulse");
  expect(css).not.toContain("tour-fade");
  expect(css).toMatch(
    /prefers-reduced-motion:[\s\S]*animation:\s*none\s*!important/,
  );
});
