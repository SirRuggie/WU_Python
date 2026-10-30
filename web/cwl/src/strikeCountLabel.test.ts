import { expect, it } from "vitest";
import { strikeCountLabel } from "./strikeCountLabel";
it.each([
  "account",
  "record",
  "history-only record",
  "war",
  "skipped war",
  "complete war",
  "total strike",
  "strike",
])("formats one and several %s counts", (noun) => {
  expect(strikeCountLabel(1, noun)).toBe(`1 ${noun}`);
  expect(strikeCountLabel(3, noun)).toBe(`3 ${noun}s`);
});
it("formats records selected", () => {
  expect(`${strikeCountLabel(1, "record")} selected`).toBe("1 record selected");
  expect(`${strikeCountLabel(3, "record")} selected`).toBe(
    "3 records selected",
  );
});
