import { describe, expect, it } from "vitest";
import { DashboardHistory, dashboardTarget } from "./dashboardHistory";
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
      "/api/cwl/auth/discord?view=home",
    );
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
