import { expect, it } from "vitest";
import { reviewPoolSelection } from "./signupReview";
import type { Account, Signup } from "./api";
const accounts = [
  { tag: "#AAA", name: "Normal", current_clan_type: null },
  { tag: "#BBB", name: "FWA account", current_clan_type: "FWA" },
] as Account[];
it("keeps eligible selections across review pool edits and lists only removed accounts", () => {
  const draft = { "#AAA": false, "#BBB": false };
  expect(reviewPoolSelection(draft, "lazy", accounts, [])).toEqual({
    retained: draft,
    removed: [],
  });
  expect(reviewPoolSelection(draft, "main", accounts, [])).toEqual({
    retained: { "#AAA": false },
    removed: ["FWA account"],
  });
  expect(draft).toEqual({ "#AAA": false, "#BBB": false });
});
it("never retains a selection that was signed up or unlinked during review", () => {
  expect(
    reviewPoolSelection({ "#AAA": false, "#GONE": false }, "lazy", accounts, [
      { tag: "#AAA" },
    ] as Signup[]),
  ).toEqual({ retained: {}, removed: ["Normal", "#GONE"] });
});
