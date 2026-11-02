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
  [{ hasDraft: false }, "Load the roster before publishing."],
  [{ canManage: false }, "You do not have permission to publish this roster."],
  [{ locked: true }, "Finish the current edit or operation before publishing."],
  [{ loading: true }, "Wait for the roster refresh to finish."],
  [
    { hasError: true },
    "Refresh the draft and resolve the error before publishing.",
  ],
  [{ archived: true }, "Publishing is unavailable for an archived season."],
  [
    { instructionsLength: 2001 },
    "Joining instructions must be 2,000 characters or fewer.",
  ],
  [{ changesReady: false }, "Review the roster changes before publishing."],
  [{ accounts: 0 }, "No signed-up accounts are in this roster yet."],
  [{ unplaced: 2 }, "Acknowledge the unplaced accounts before publishing."],
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
