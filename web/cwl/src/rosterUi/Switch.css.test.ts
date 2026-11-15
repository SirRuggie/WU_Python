import { readFileSync } from "node:fs";
import { expect, it } from "vitest";

const css = readFileSync(new URL("./Switch.css", import.meta.url), "utf8");

it("moves the thumb in 150ms with an ease-out curve and not at all for reduced motion", () => {
  expect(css).toContain("transform 150ms cubic-bezier(0.23, 1, 0.32, 1)");
  expect(css).toMatch(
    /prefers-reduced-motion: reduce\) \{[^}]*\{[^}]*transition: none/,
  );
});

it("keeps a 44px hit area, a visible focus ring and a red problem state", () => {
  expect(css).toContain("min-height: 44px");
  expect(css).toContain("input:focus-visible + .wu-switch-track");
  expect(css).toContain("outline: 2px solid var(--wu-focus)");
  expect(css).toContain(".wu-switch.is-problem input:checked");
});
