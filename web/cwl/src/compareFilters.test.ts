import { describe, expect, it } from "vitest";
import { comparisonFilters } from "./compareFilters";
import type { RosterAccount, RosterClan } from "./roster";
const clans = [
  { tag: "#A", cwl_league: "Crystal League I" },
  { tag: "#B", cwl_league: "Master League II" },
] as RosterClan[];
const accounts = [
  { tag: "#1", assigned_clan_tag: "#A", town_hall: 18 },
  { tag: "#2", assigned_clan_tag: "#A", town_hall: null },
  { tag: "#3", assigned_clan_tag: "#B", town_hall: 17 },
  { tag: "#4", assigned_clan_tag: "#OTHERPOOL", town_hall: 14 },
] as RosterAccount[];
describe("Compare filter facets", () => {
  it("scopes TH choices to assigned accounts in this pool and retains selected zero matches", () => {
    const result = comparisonFilters(accounts, clans, ["#A"], [], ["TH 16"]);
    expect(result.townHalls.map((item) => item.value)).toEqual([
      "TH 18",
      "TH 17",
      "TH 16",
      "Unknown TH",
    ]);
    expect(result.townHalls.find((item) => item.value === "TH 16")?.count).toBe(
      0,
    );
    expect(result.count).toBe(0);
  });
  it("counts each facet with only the other section applied", () => {
    const result = comparisonFilters(
      accounts,
      clans,
      ["#A", "#B"],
      ["Crystal League I"],
      ["TH 18"],
    );
    expect(result.count).toBe(1);
    expect(
      result.townHalls.find((item) => item.value === "Unknown TH")?.count,
    ).toBe(1);
    expect(result.townHalls.find((item) => item.value === "TH 17")?.count).toBe(
      0,
    );
    expect(
      result.leagues.find((item) => item.value === "Crystal League I")?.count,
    ).toBe(1);
    expect(
      result.leagues.find((item) => item.value === "Master League II")?.count,
    ).toBe(0);
  });
  it("counts only chosen clans but does not lose the full pool's options", () => {
    const result = comparisonFilters(accounts, clans, [], [], []);
    expect(result.count).toBe(0);
    expect(result.townHalls).toHaveLength(3);
    expect(result.leagues.every((item) => item.count === 0)).toBe(true);
  });
});
