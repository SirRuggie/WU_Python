import { expect, it } from "vitest";
import { parseWeight, pasteWeights, copyRows } from "./model";
it("accepts shorthand weights and blank, rejects ambiguous values", () => {
  expect(parseWeight("149")).toBe(149000);
  expect(parseWeight("")).toBeNull();
  for (const value of ["149k", "149000", "0", "-1", "1.5", "=1", "1\t2"])
    expect(() => parseWeight(value)).toThrow();
});
it("pastes an Excel column without spilling past the roster", () => {
  expect(pasteWeights("149\r\n150\r\n", 2)).toEqual(["149", "150"]);
  expect(() => pasteWeights("149\n150", 1)).toThrow();
  expect(() => pasteWeights("149\t150", 2)).toThrow();
});
it("copies player tags and safely quotes external names", () => {
  expect(
    copyRows(
      [
        {
          tag: "#P2Y",
          name: "=bad()",
          town_hall: 16,
          weight: 149000,
          revision: 1,
        },
      ],
      { "#P2Y": "149" },
    ),
  ).toContain("#P2Y\t'=bad()\t16\t149");
});
