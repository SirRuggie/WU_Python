import { describe, expect, it } from "vitest";
import { dashboardPath, dashboardTarget } from "./dashboardHistory";
import { parseResultsState, resultsStateQuery } from "./resultsUrlState";

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
});
