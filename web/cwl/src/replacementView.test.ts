import { expect, it } from "vitest";
import { compactWeight, enteredWeight } from "./replacementView";
it("converts compact recruit weights and displays full weights", () => {
  expect(enteredWeight("149")).toBe(149000);
  expect(enteredWeight("149000")).toBe(149000);
  expect(compactWeight(149500)).toBe("149.5k");
});
