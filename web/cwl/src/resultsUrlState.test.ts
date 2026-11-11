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
  it("leaves defaults out of the query", () => {
    expect(
      resultsStateQuery({ pool: "main", outcome: "all", sort: "name" }),
    ).toBe("pool=main");
  });
  it("round-trips through the dashboard route for both pages", () => {
    for (const [path, view] of [
      ["/cwl/results", "participation"],
      ["/cwl/bonuses", "bonuses"],
    ] as const) {
      const route = dashboardTarget(
        "?season=4&pool=lazy&clan=%232YQ&outcome=meets&sort=attacks-desc&step=approval",
        path,
      );
      expect(route.view).toBe(view);
      expect(route.resultsState).toBe(
        "pool=lazy&clan=%232YQ&outcome=meets&sort=attacks-desc&step=approval",
      );
      expect(dashboardPath(route)).toBe(
        `${path}?season=4&pool=lazy&clan=%232YQ&outcome=meets&sort=attacks-desc&step=approval`,
      );
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
