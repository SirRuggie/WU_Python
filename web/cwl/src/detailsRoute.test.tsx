// @vitest-environment happy-dom
import { expect, it } from "vitest";
import { DashboardHistory } from "./dashboardHistory";
import { detailsUrl } from "./detailsNavigation";

it.each(["roster", "publish", "readiness"])(
  "preserves the %s account and marker on focus/access route refresh, then Next",
  (path) => {
    history.replaceState(
      { wuDashboardIndex: 2, wuActionPanel: "details:test" },
      "",
      `/cwl/${path}?season=1&account=%23FIRST`,
    );
    const route = {
      view:
        path === "publish"
          ? "publication"
          : path === "readiness"
            ? "declaration"
            : "roster",
      season: "1",
    } as const;
    const controller = new DashboardHistory(history);
    controller.write(route, false);
    expect(location.search).toContain("account=%23FIRST");
    expect(history.state.wuActionPanel).toBe("details:test");
    history.replaceState(history.state, "", detailsUrl("#NEXT"));
    expect(location.search).toContain("account=%23NEXT");
    controller.write({ ...route, season: "2" }, false);
    expect(location.search).not.toContain("account");
    expect(history.state.wuActionPanel).toBeUndefined();
  },
);
