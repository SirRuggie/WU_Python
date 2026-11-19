import { expect, it } from "vitest";
import {
  isTownHallHistoryTarget,
  townHallHistoryValue,
} from "./townHallHistory";

it("supports list, settings and level paths while leaving other history unchanged", () => {
  for (const target of [
    "/manage/town-halls",
    "/api/cwl/manage/town-halls/19",
    "/manage/town-halls/settings",
  ])
    expect(isTownHallHistoryTarget(target)).toBe(true);
  for (const target of [
    "/manage/town-halls/add",
    "/manage/town-halls/019",
    "/manage/operations/fwa_weight/19",
  ])
    expect(isTownHallHistoryTarget(target)).toBe(false);
  expect(
    townHallHistoryValue("/manage/content/item", "emoji", "unchanged"),
  ).toBeNull();
  expect(
    townHallHistoryValue("/manage/town-halls/19", "min", 181000),
  ).toBeNull();
});

it("shows only the emoji name while preserving exact restore values", () => {
  const before = Object.freeze({ emoji: "<:TH_19A:1571025137896005783>" });
  const shown = townHallHistoryValue(
    "/manage/town-halls/19",
    "emoji",
    before.emoji,
  );
  expect(shown).toBe("TH_19A");
  expect(shown).not.toContain("1571025137896005783");
  expect(shown).not.toContain("<:");
  expect(before.emoji).toBe("<:TH_19A:1571025137896005783>");
  expect(townHallHistoryValue("/manage/town-halls/19", "emoji", "")).toBe(
    "None",
  );
  expect(
    townHallHistoryValue(
      "/manage/town-halls/19",
      "emoji",
      "1571025137896005783",
    ),
  ).toBe("Emoji unavailable");
});
