import { readFileSync, statSync } from "node:fs";
import { expect, it } from "vitest";
import { steps } from "./model";

it("ships every step's local WebP within its budget and records provenance", () => {
  for (const art of new Set(steps.map((step) => step.art))) {
    const path = `public/assets/tour/${art}.webp`;
    expect(statSync(path).size).toBeLessThanOrEqual(80_000);
    const data = readFileSync(path);
    expect(data.toString("ascii", 8, 12)).toBe("WEBP");
  }
  const source = readFileSync("public/assets/tour/SOURCES.md", "utf8");
  expect(source).toContain("Ruggie supplied");
  expect(source).toContain("https://fankit.supercell.com/");
});

it("uses fade-only reduced motion, hides confetti and keeps 44px controls", () => {
  const css = readFileSync("src/memberTour/tour.css", "utf8");
  const reduced = css.slice(css.indexOf("@media (prefers-reduced-motion"));
  expect(reduced).toContain("animation: none !important");
  expect(reduced).toMatch(/\.tour-confetti\s*\{\s*display: none/);
  expect(reduced).toContain("tour-fade 120ms");
  expect(css).toContain("min-height: 44px");
});
