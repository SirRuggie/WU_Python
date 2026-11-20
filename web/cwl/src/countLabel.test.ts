import { expect, it } from "vitest";
import { countLabel, countNoun } from "./countLabel";

it.each([
  [0, "0 accounts"],
  [1, "1 account"],
  [2, "2 accounts"],
  [1000, "1,000 accounts"],
  [1234567, "1,234,567 accounts"],
] as const)("formats %s without changing the count", (count, expected) =>
  expect(countLabel(count, "account")).toBe(expected),
);
it("accepts an explicit irregular plural", () => {
  expect(countLabel(1, "person", "people")).toBe("1 person");
  expect(countLabel(2, "person", "people")).toBe("2 people");
});
it("preserves phrase verb agreement and split or capped count markup", () => {
  expect(countLabel(1, "account is", "accounts are")).toBe("1 account is");
  expect(countLabel(1000, "account is", "accounts are")).toBe(
    "1,000 accounts are",
  );
  expect(countNoun(1, "strike")).toBe("strike");
  expect(countNoun(1000, "strike")).toBe("strikes");
  expect(`100+ ${countNoun(100, "signup change")}`).toBe("100+ signup changes");
});
