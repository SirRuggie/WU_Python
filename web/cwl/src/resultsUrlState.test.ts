import { describe, expect, it } from "vitest";
import { dashboardPath, dashboardTarget } from "./dashboardHistory";
import { parseResultsState, resultsStateQuery } from "./resultsUrlState";
import { bonusStepHref } from "./BonusStepBar";

describe("Results and Bonus URL state", () => {
  it("parses only known values", () => {
    expect(
      parseResultsState(
        "pool=lazy&clan=%232YQ&outcome=below&sort=stars-desc&step=draw",
      ),
    ).toEqual({
      pool: "lazy",
      clan: "#2YQ",
      outcome: "below",
      sort: "stars-desc",
      step: "draw",
    });
    expect(
      parseResultsState("pool=x&clan=bad&outcome=x&sort=th-asc&step=x"),
    ).toEqual({});
  });
  it("maps the old step names and keeps the new ones", () => {
    for (const [old, now] of [
      ["eligibility", "rules"],
      ["approval", "approve"],
      ["announcement", "announce"],
      ["results", "results"],
      ["rules", "rules"],
      ["draw", "draw"],
      ["approve", "approve"],
      ["announce", "announce"],
    ] as const)
      expect(parseResultsState(`step=${old}`).step).toBe(now);
  });
  it("leaves defaults out of the query", () => {
    expect(
      resultsStateQuery({ pool: "main", outcome: "all", sort: "name" }),
    ).toBe("pool=main");
  });
  it("opens one page from /cwl/results and the older /cwl/bonuses", () => {
    for (const path of ["/cwl/results", "/cwl/bonuses"] as const) {
      const route = dashboardTarget(
        "?season=4&pool=lazy&clan=%232YQ&outcome=meets&sort=attacks-desc&step=approval",
        path,
      );
      expect(route.view).toBe("participation");
      // The old step name opens the renamed step.
      expect(route.resultsState).toBe(
        "pool=lazy&clan=%232YQ&outcome=meets&sort=attacks-desc&step=approve",
      );
      // Both addresses write the one canonical path.
      expect(dashboardPath(route)).toBe(
        "/cwl/results?season=4&pool=lazy&clan=%232YQ&outcome=meets&sort=attacks-desc&step=approve",
      );
      expect(
        dashboardTarget("?view=bonuses&season=4&pool=lazy&step=draw").view,
      ).toBe("participation");
    }
  });
  it("keeps the keys off other pages", () => {
    const route = dashboardTarget("?season=4&pool=lazy", "/cwl/exports");
    expect(route.resultsState).toBeUndefined();
    expect(
      dashboardPath({
        view: "exports",
        season: "4",
        resultsState: "pool=lazy",
      }),
    ).toBe("/cwl/exports?season=4");
  });
  it("keeps the new outcome keys and links incomplete players with one outcome", () => {
    for (const outcome of ["did_not_join", "filler", "not_assigned"] as const)
      expect(parseResultsState(`outcome=${outcome}`).outcome).toBe(outcome);
    expect(
      bonusStepHref("4", "results", "main", "#2YQ", "not_checked").query,
    ).toBe("pool=main&clan=%232YQ&outcome=not_checked");
    expect(bonusStepHref("4", "results", "main", "#2YQ").query).toBe(
      "pool=main&clan=%232YQ",
    );
    expect(bonusStepHref("4", "draw", "main", "#2YQ", "partial").query).toBe(
      "pool=main&clan=%232YQ&step=draw",
    );
  });
});
