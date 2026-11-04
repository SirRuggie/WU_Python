import { expect, it } from "vitest";
import { publicationBlockingReason as reason } from "./publicationBlockingReason";
const ready = {
  hasDraft: true,
  canManage: true,
  locked: false,
  loading: false,
  hasError: false,
  archived: false,
  instructionsLength: 2000,
  changesReady: true,
  accounts: 1,
  unplaced: 0,
  acknowledged: false,
};
it.each([
  [{ hasDraft: false }, "Load the roster. Then publish."],
  [{ canManage: false }, "You do not have permission to publish this roster."],
  [{ locked: true }, "Finish the current edit. Then publish."],
  [{ loading: true }, "Wait for the roster refresh to finish."],
  [
    { hasError: true },
    "Refresh the draft and fix the error. Then publish.",
  ],
  [{ archived: true }, "You cannot publish an archived season."],
  [
    { instructionsLength: 2001 },
    "Joining instructions must not be more than 2,000 characters.",
  ],
  [
    { changesReady: false },
    "Refresh the draft to load the latest roster changes.",
  ],
  [{ accounts: 0 }, "No signed-up accounts are in this roster yet."],
  [{ unplaced: 2 }, "Confirm that you know about the unplaced accounts. Then publish."],
] as const)("explains blocked Publish gate %j", (change, text) =>
  expect(reason({ ...ready, ...change })).toBe(text),
);
it("reports the first failure and clears when the existing checks pass", () => {
  expect(
    reason({ ...ready, canManage: false, archived: true, changesReady: false }),
  ).toBe("You do not have permission to publish this roster.");
  expect(reason(ready)).toBe("");
  expect(reason({ ...ready, unplaced: 2, acknowledged: true })).toBe("");
});

it("leaves the comparison loading status to explain pending reads, and asks Refresh after failure", () => {
  expect(
    reason({ ...ready, changesReady: false, comparisonStatus: "loading" }),
  ).toBe("");
  expect(
    reason({ ...ready, changesReady: false, comparisonStatus: "error" }),
  ).toBe("Refresh the draft to load the latest roster changes.");
});
