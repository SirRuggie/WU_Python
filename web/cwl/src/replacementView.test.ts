import { expect, it } from "vitest";
import {
  compactWeight,
  enteredWeight,
  parseWeights,
  weightsText,
} from "./replacementView";
it("converts compact recruit weights and displays full weights", () => {
  expect(enteredWeight("149")).toBe(149000);
  expect(enteredWeight("149000")).toBe(149000);
  expect(compactWeight(149500)).toBe("149.5k");
});
it("reads several recruit weights and names the value it cannot read", () => {
  expect(parseWeights("143, 173k 150000").weights).toEqual([
    143000, 173000, 150000,
  ]);
  expect(parseWeights("143.5").weights).toEqual([143500]);
  expect(parseWeights("143, abc").error).toContain("“abc”");
  expect(parseWeights("0").error).toContain("“0”");
  expect(parseWeights("1,2,3,4,5,6").error).toBe("Enter up to 5 weights.");
  expect(parseWeights("  ").error).toBe("Enter a weight.");
  expect(weightsText([143000, 143500])).toBe("143, 143.5");
});
