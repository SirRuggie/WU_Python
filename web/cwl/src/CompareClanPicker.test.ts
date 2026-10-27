import { it, expect } from "vitest";
import { sortChosenComparisonClans } from "./CompareClanPicker";
import type { RosterClan } from "./roster";
it("sorts every chosen clan even when another league is hidden", () => {
  const clans = [
    { tag: "A", name: "Zulu", cwl_league: "Master League I" },
    { tag: "B", name: "Alpha", cwl_league: "Crystal League I" },
  ] as RosterClan[];
  const chosen = ["A", "B"];
  expect(sortChosenComparisonClans(clans, chosen, "name")).toEqual(["B", "A"]);
  expect(sortChosenComparisonClans(clans, chosen, "league_desc")).toEqual([
    "A",
    "B",
  ]);
  expect(chosen).toEqual(["A", "B"]);
});
