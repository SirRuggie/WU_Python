import { expect, it } from "vitest";
import { countLabel } from "./countLabel";

it.each([
  [0, "0 accounts"],
  [1, "1 account"],
  [2, "2 accounts"],
] as const)("formats %s without changing the count", (count, expected) =>
  expect(countLabel(count, "account")).toBe(expected),
);
it("accepts an explicit irregular plural", () => {
  expect(countLabel(1, "person", "people")).toBe("1 person");
  expect(countLabel(2, "person", "people")).toBe("2 people");
});
