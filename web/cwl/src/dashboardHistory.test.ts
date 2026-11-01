import { describe, expect, it } from "vitest";
import {
  DashboardHistory,
  dashboardTarget,
  dashboardPath,
} from "./dashboardHistory";
import { loginPath } from "./memberLinks";
function fixture() {
  const entries = [{ state: null as unknown, url: "/" }];
  let cursor = 0;
  const movements: number[] = [];
  const port = {
    get state() {
      return entries[cursor].state;
    },
    replaceState(state: unknown, _unused: string, url?: string | URL | null) {
      entries[cursor] = { state, url: String(url || entries[cursor].url) };
    },
    pushState(state: unknown, _unused: string, url?: string | URL | null) {
      entries.splice(++cursor);
      entries.push({ state, url: String(url) });
    },
    go(delta: number) {
      movements.push(delta);
      cursor += delta;
    },
  };
  const controller = new DashboardHistory(port);
  return {
    controller,
    port,
    entries,
    movements,
    travel(delta: number) {
      cursor += delta;
      return port.state;
    },
    current: () => entries[cursor],
  };
}
describe("dashboard browser history", () => {
  it("accepts internal staff routes and seasons while retaining the OAuth member allowlist", () => {
    expect(dashboardTarget("?view=clan-management&season=12")).toEqual({
      view: "clan-management",
      season: "12",
    });
    expect(dashboardTarget("?view=https://evil.test&season=bad")).toEqual({
      view: "home",
      season: "",
    });
    expect(dashboardTarget("?view=signups&season=12")).toEqual({
      view: "signup",
      season: "12",
    });
    expect(loginPath("?view=access&season=12", false)).toBe(
      "/api/cwl/auth/discord?view=access",
    );
  });
  it("ignores same-index overlay history entries without invoking the dirty-route guard", () => {
    const f = fixture();
    f.controller.write({ view: "roster", season: "12" }, true);
    const allow = () => {
      throw Error("A same-route overlay must not prompt");
    };
    expect(
      f.controller.pop({ wuDashboardIndex: 1, wuActionPanel: "assign" }, allow),
    ).toBe(false);
    expect(f.current().url).toContain("roster");
  });
  it("records visits, updates season in place, and accepts Back and Forward", () => {
    const f = fixture();
    f.controller.write({ view: "tickets", season: "12" }, true);
    f.controller.write({ view: "reminders", season: "12" }, true);
    f.controller.write({ view: "reminders", season: "13" }, false);
    expect(f.entries).toHaveLength(3);
    expect(f.controller.pop(f.travel(-1), () => true)).toBe(true);
    expect(f.current().url).toContain("tickets");
    expect(f.controller.pop(f.travel(1), () => true)).toBe(true);
    expect(f.current().url).toContain("season=13");
  });
  it("cancels multi-entry Back without losing the current draft or forward stack", () => {
    const f = fixture();
    f.controller.write({ view: "tickets", season: "" }, true);
    f.controller.write({ view: "reminders", season: "12" }, true);
    expect(f.controller.pop(f.travel(-2), () => false)).toBe(false);
    expect(f.movements).toEqual([2]);
    expect(f.controller.pending).toBe(true);
    f.controller.write({ view: "home", season: "" }, true);
    expect(f.entries).toHaveLength(3);
    expect(
      f.controller.pop(f.port.state, () => {
        throw Error("Must not prompt twice");
      }),
    ).toBe(false);
    expect(f.controller.pending).toBe(false);
    expect(f.current().url).toContain("reminders");
  });
  it("handles a queued second Back while restoring a canceled visit", () => {
    const f = fixture();
    f.controller.write({ view: "tickets", season: "" }, true);
    f.controller.write({ view: "reminders", season: "12" }, true);
    f.controller.pop(f.travel(-1), () => false);
    expect(
      f.controller.pop(f.travel(-2), () => {
        throw Error("Must not prompt during restoration");
      }),
    ).toBe(false);
    expect(f.current().url).toContain("reminders");
    f.controller.pop(f.port.state, () => true);
    expect(f.controller.pending).toBe(false);
  });
  it("cancels Forward and allows subsequent Back after cancellation", () => {
    const f = fixture();
    f.controller.write({ view: "tickets", season: "" }, true);
    f.controller.pop(f.travel(-1), () => true);
    expect(f.controller.pop(f.travel(1), () => false)).toBe(false);
    expect(f.movements).toEqual([-1]);
    f.controller.pop(f.port.state, () => true);
    expect(f.controller.pop(f.travel(1), () => true)).toBe(true);
    expect(f.controller.pop(f.travel(-1), () => true)).toBe(true);
  });
});

it("preserves announcement steps while rejecting arbitrary step values", () => {
  expect(dashboardTarget("?view=publication&season=12&step=announce")).toEqual({
    view: "publication",
    season: "12",
    step: "announce",
  });
  expect(dashboardTarget("?view=publication&step=unsafe")).toEqual({
    view: "publication",
    season: "",
  });
  const history = fixture();
  history.controller.write(
    { view: "publication", season: "12", step: "announce" },
    true,
  );
  expect(history.current().url).toBe("/cwl/publish?step=announce&season=12");
});

it("uses clean member paths and only retains seasons on CWL staff pages", () => {
  for (const [view, path] of [
    ["signup", "/signup"],
    ["assignments", "/assignments"],
    ["todo", "/tasks"],
    ["home", "/"],
    ["events", "/events"],
    ["wars", "/wars"],
    ["search", "/search"],
  ] as const) {
    expect(dashboardPath({ view, season: "1" })).toBe(path);
    expect(dashboardTarget("", path).view).toBe(view);
  }
  expect(dashboardPath({ view: "clan-management", season: "1" })).toBe(
    "/clans",
  );
  expect(dashboardPath({ view: "roster", season: "2" })).toBe(
    "/cwl/roster?season=2",
  );
});

it("uses a clean clan weight path and preserves old entry links", () => {
  expect(dashboardPath({ view: "weight-trial", season: "1" })).toBe(
    "/clan-weights",
  );
  for (const path of [
    "/clan-weights",
    "/weight",
    "/weights",
    "/weight-trial",
  ]) {
    expect(dashboardTarget("", path).view).toBe("weight-trial");
  }
  expect(dashboardTarget("?view=weight-trial&season=1").view).toBe(
    "weight-trial",
  );
});

it("gives saved signups a distinct history entry and restores the tab on Back/Forward", () => {
  const f = fixture();
  f.controller.write({ view: "signup", season: "99" }, true);
  f.controller.write(
    { view: "signup", season: "99", signupPanel: "saved" },
    true,
  );
  expect(f.current().url).toBe("/my-signups");
  expect(dashboardTarget("", f.current().url)).toEqual({
    view: "signup",
    season: "",
    signupPanel: "saved",
  });
  expect(f.controller.pop(f.travel(-1), () => true)).toBe(true);
  expect(f.current().url).toBe("/signup");
  expect(dashboardTarget("", f.current().url).signupPanel).toBeUndefined();
  expect(f.controller.pop(f.travel(1), () => true)).toBe(true);
  expect(f.current().url).toBe("/my-signups");
});
it("normalizes member trailing slashes without overriding path with a conflicting view", () => {
  for (const [path, view] of [
    ["/signup/", "signup"],
    ["/assignments/", "assignments"],
    ["/tasks/", "todo"],
    ["/wars/", "wars"],
    ["/events/", "events"],
    ["/search/", "search"],
  ] as const) {
    expect(dashboardTarget("?view=roster", path).view).toBe(view);
    expect(dashboardPath(dashboardTarget("?season=999", path))).toBe(
      path.slice(0, -1),
    );
  }
});

it("round trips every staff CWL destination, including legacy links and OAuth returns", async () => {
  const { cwlPaths } = await import("./staffLinks");
  for (const [view, path] of Object.entries(cwlPaths)) {
    const legacy = dashboardTarget(`?view=${view}&season=12`);
    const expected = dashboardPath(legacy);
    const canonical = view === "manage-signups" ? "roster" : view;
    expect(
      expected.startsWith(view === "manage-signups" ? "/cwl/roster" : path),
    ).toBe(true);
    for (const suffix of ["", "/"]) {
      const target = dashboardTarget("?view=access&season=12", path + suffix);
      expect(target.view).toBe(canonical);
      expect(dashboardPath(target)).toBe(expected);
      expect(loginPath("?view=access&season=12", false, path + suffix)).toBe(
        `/api/cwl/auth/discord?view=${canonical}&season=12`,
      );
    }
  }
  expect(
    dashboardTarget("?view=publication&step=announce", "/cwl/roster").step,
  ).toBeUndefined();
  expect(
    dashboardPath(dashboardTarget("?step=announce&season=12", "/cwl/publish")),
  ).toBe("/cwl/publish?step=announce&season=12");
  expect(loginPath("?season=bad&step=unsafe", false, "/cwl/publish")).toBe(
    "/api/cwl/auth/discord?view=publication",
  );
  expect(loginPath("?view=roster", false, "/tasks")).toBe(
    "/api/cwl/auth/discord?view=todo",
  );
});

it("restores bounded activity context only for its own destination", async () => {
  const { activityContext } = await import("./dashboardHistory");
  const state = {
    wuActivity: { view: "todo", filter: "#ABC123", kind: "cwl" },
  };
  expect(activityContext(state, "todo")).toEqual({
    activityFilter: "#ABC123",
    activityKind: "cwl",
  });
  expect(activityContext(state, "wars")).toEqual({});
  expect(activityContext(state, "signup")).toEqual({});
  expect(
    activityContext(
      { wuActivity: { view: "todo", filter: "<script>", kind: "evil" } },
      "todo",
    ),
  ).toEqual({ activityFilter: "" });
  expect(
    dashboardPath({
      view: "todo",
      season: "",
      activityFilter: "#ABC123",
      activityKind: "cwl",
    }),
  ).toBe("/tasks");
});

it("keeps each task handoff with its history entry through Back and Forward", async () => {
  const { activityContext } = await import("./dashboardHistory");
  const f = fixture();
  f.controller.write({ view: "wars", season: "", activityKind: "cwl" }, true);
  f.controller.write(
    { view: "todo", season: "", activityKind: "cwl", activityFilter: "#ABC" },
    true,
  );
  f.controller.write({ view: "home", season: "" }, true);
  expect(f.controller.pop(f.travel(-1), () => true)).toBe(true);
  expect(activityContext(f.current().state, "todo")).toEqual({
    activityFilter: "#ABC",
    activityKind: "cwl",
  });
  expect(f.controller.pop(f.travel(-1), () => true)).toBe(true);
  expect(activityContext(f.current().state, "wars")).toEqual({
    activityFilter: "",
    activityKind: "cwl",
  });
  expect(f.controller.pop(f.travel(1), () => true)).toBe(true);
  expect(activityContext(f.current().state, "todo").activityFilter).toBe(
    "#ABC",
  );
});

it.each([false, true])(
  "tour Back restores its own entry without replacing a prior entry (legacy=%s)",
  (legacy) => {
    const f = fixture();
    f.controller.write({ view: "signup", season: "" }, true);
    if (legacy) f.entries[0].state = null;
    const prior = { ...f.entries[0] };
    const state = f.travel(-1);
    f.controller.restoreTourEntry(state);
    expect(f.controller.pending).toBe(true);
    expect(f.movements).toEqual([1]);
    expect(f.controller.pop(f.port.state, () => true)).toBe(false);
    expect(f.controller.pending).toBe(false);
    f.controller.write({ view: "signup", season: "" }, false);
    expect(f.entries[0]).toEqual(prior);
    expect(f.entries).toHaveLength(2);
    expect(f.current().url).toBe("/signup");
  },
);

it("round-trips only a valid replacement clan and never carries it into other destinations", () => {
  const route = dashboardTarget("?clan=%23Q2Y", "/clans/replacements");
  expect(route).toEqual({
    view: "replacements",
    season: "",
    replacementClan: "#Q2Y",
  });
  expect(dashboardPath(route)).toBe("/replacements?clan=%23Q2Y");
  expect(
    dashboardTarget("?clan=https://evil.test", "/clans/replacements")
      .replacementClan,
  ).toBeUndefined();
  expect(dashboardPath({ ...route, view: "strikes" })).toBe("/strikes");
  expect(
    dashboardTarget("?clan=%23Q2Y", "/clans/strikes").replacementClan,
  ).toBeUndefined();
});

it("keeps encoded clan/player weight targets across path roundtrips", () => {
  const route = {
    view: "weight-trial" as const,
    season: "",
    weightPlayer: "#P2Y",
    weightClan: "#R2Y",
  };
  const path = dashboardPath(route);
  expect(path).toBe("/clan-weights?player=%23P2Y&clan=%23R2Y");
  expect(
    dashboardTarget(path.slice(path.indexOf("?")), "/clan-weights"),
  ).toEqual(route);
  expect(
    dashboardTarget("?player=https://evil.example&clan=bad", "/clan-weights")
      .weightPlayer,
  ).toBeUndefined();
});

it("round-trips replacement clan and player targets without losing the flow origin", () => {
  const target = dashboardTarget(
    "?clan=%23R2Y&tag=%23P2Y&from=strikes",
    "/clans/replacements",
  );
  expect(target).toMatchObject({
    replacementClan: "#R2Y",
    replacementTag: "#P2Y",
    flowFrom: "strikes",
  });
  expect(
    dashboardTarget(
      new URL(dashboardPath(target), "https://test.invalid").search,
      "/clans/replacements",
    ),
  ).toEqual(target);
  expect(
    dashboardTarget("?tag=%23P2Y&from=replacements", "/clans/strikes"),
  ).toMatchObject({ strikeTag: "#P2Y", flowFrom: "replacements" });
  expect(
    dashboardTarget("?tag=not-a-tag&from=home", "/clans/replacements")
      .replacementTag,
  ).toBeUndefined();
});

it("round-trips family clan routes without stealing Strikes or Replacements", () => {
  for (const path of [
    "/clans/reminders",
    "/clans/history",
    "/clans/%23P0LYQ",
    "/clans/%23P0LYQ/war-reminders",
    "/clans/%23P0LYQ/roles",
  ]) {
    const route = dashboardTarget("", path);
    expect(route.view).toBe("clan-management");
    expect(dashboardPath(route)).toBe(path);
  }
  expect(dashboardTarget("", "/clans/strikes").view).toBe("strikes");
  expect(dashboardTarget("", "/clans/replacements").view).toBe("replacements");
  expect(dashboardTarget("", "/clans/%ZZ").view).toBe("home");
  expect(dashboardTarget("", "/clans/%23P0LYQ/not-a-section").view).toBe(
    "home",
  );
});

it("preserves the activity tab and every threshold through route and login state", () => {
  const query =
    "?activity_view=all&wars=5&quiet=14&raids=2&priority=high&min_weight=100000&max_weight=150000&direction=asc&sort=weight&no_activity=1";
  const route = dashboardTarget(query, "/strikes");
  expect(route.view).toBe("strikes");
  const restored = new URL(dashboardPath(route), "https://fixture");
  for (const [key, value] of new URLSearchParams(query))
    expect(restored.searchParams.get(key)).toBe(value);
  const login = new URL(loginPath(query, false, "/strikes"), "https://fixture");
  expect(login.searchParams.get("view")).toBe("strikes");
  for (const [key, value] of new URLSearchParams(query))
    expect(login.searchParams.get(key)).toBe(value);
});
