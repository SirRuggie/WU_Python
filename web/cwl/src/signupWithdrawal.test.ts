import { expect, it, vi } from "vitest";
import {
  withdrawInOrder,
  signupPlacementNotice,
  withdrawConfirmation,
} from "./signupWithdrawal";

it("stops on an uncertain failure without retrying or deleting later accounts", async () => {
  const error = new Error("Connection lost");
  const remove = vi
    .fn()
    .mockResolvedValueOnce({ ok: true })
    .mockRejectedValueOnce(error);
  const result = await withdrawInOrder(["#ONE", "#TWO", "#THREE"], remove);
  expect([...result.removed]).toEqual(["#ONE"]);
  expect(result.error).toBe(error);
  expect(remove.mock.calls).toEqual([["#ONE"], ["#TWO"]]);
});
it("confirms every successful withdrawal and avoids duplicate requests", async () => {
  const remove = vi.fn().mockResolvedValue({ ok: true });
  const result = await withdrawInOrder(["#ONE", "#TWO", "#ONE"], remove);
  expect([...result.removed]).toEqual(["#ONE", "#TWO"]);
  expect(result.error).toBeNull();
  expect(remove).toHaveBeenCalledTimes(2);
});

it("names exactly the placed accounts in guidance and withdrawal confirmation", () => {
  const rows = [
    { tag: "#A", player_name: "Alpha", has_staff_placement: true },
    { tag: "#B", player_name: "Beta", has_staff_placement: false },
  ];
  expect(signupPlacementNotice(rows)).toContain("for Alpha and alert staff");
  expect(signupPlacementNotice(rows)).not.toContain("Beta");
  const confirmation = withdrawConfirmation(rows);
  expect(confirmation).toContain("Alpha (#A)");
  expect(confirmation).toContain("Beta (#B)");
  expect(confirmation).toContain(
    "Clan assignments will be cleared for: Alpha.",
  );
  expect(withdrawConfirmation([rows[1]])).not.toContain(
    "Clan assignments will be cleared",
  );
});
