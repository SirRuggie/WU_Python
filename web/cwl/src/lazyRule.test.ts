import { describe, expect, it } from "vitest";
import { lazyQualifies } from "./lazyRule";

describe("Lazy participation rule", () => {
  it.each([
    [0, 0, false],
    [2, 9, false],
    [3, 7, false],
    [3, 8, true],
    [3, 9, true],
    [4, 0, true],
    [7, 21, true],
  ])("evaluates %i attacks and %i stars", (attacks, stars, expected) => {
    expect(lazyQualifies(attacks, stars)).toBe(expected);
  });
});
