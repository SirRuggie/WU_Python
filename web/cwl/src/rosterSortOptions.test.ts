import { expect, it } from "vitest";
import { rosterSortOptions, rosterSortShortLabels } from "./rosterSortOptions";
it("gives every existing sort an explicit short phone label", () => {
  expect(Object.keys(rosterSortShortLabels).sort()).toEqual(
    rosterSortOptions.map(([value]) => value).sort(),
  );
  expect(rosterSortShortLabels.weight_desc).toBe("Weight ↓");
  expect(rosterSortShortLabels.weight_asc).toBe("Weight ↑");
  expect(
    Object.values(rosterSortShortLabels).every((label) => label.trim()),
  ).toBe(true);
});
