import { expect, it } from "vitest";
import { cardFor, milestone, rickrollUrl } from "./model";

it("keeps the fifteen supplied cards within copy limits", () => {
  for (const branch of ["yes", "no"] as const) {
    for (let number = 1; number <= 15; number += 1) {
      const card = cardFor(number, branch, 135);
      expect(card.title.length, `title ${number}`).toBeLessThanOrEqual(40);
      expect(card.body.length, `body ${number}`).toBeLessThanOrEqual(120);
      for (const button of card.buttons)
        expect(button.length, `button ${number}`).toBeLessThanOrEqual(18);
    }
  }
});

it("uses the selected bait branch and live signup count", () => {
  expect(cardFor(3, "yes", 42).body).toContain("hit Yes");
  expect(cardFor(3, "no", 42).body).toContain("pressed No");
  expect(cardFor(2, "yes", 42).body).toBe("Deleted 42/42 signups");
  expect(cardFor(6, "no", 42).body).toContain("All 42 signups are safe");
  expect(cardFor(14, "no", 42).body).toBe(
    "Next time you see a big scary button, maybe ask Ruggie to supervise you. Just a thought.",
  );
});

it("maps only specified visible milestone cards and uses Tenor", () => {
  expect(milestone(3)).toBe("prank_jumpscare_seen");
  expect(milestone(10)).toBe("prank_rickroll_seen");
  expect([11, 12, 13, 14].map(milestone)).toEqual([
    "prank_encore_1",
    "prank_encore_2",
    "prank_encore_3",
    "prank_encore_4",
  ]);
  expect(milestone(4)).toBeNull();
  expect(rickrollUrl).toBe(
    "https://media.tenor.com/x8v1oNUOmg4AAAAM/rickroll-roll.gif",
  );
});
