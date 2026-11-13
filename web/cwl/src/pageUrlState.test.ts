// @vitest-environment happy-dom
import { beforeEach, describe, expect, it } from "vitest";
import { dashboardPath, dashboardTarget } from "./dashboardHistory";
import {
  pageParamQuery,
  parsePageParam,
  replacePageParam,
} from "./pageUrlState";

describe("page tab and filter params", () => {
  beforeEach(() => window.history.replaceState({ keep: 1 }, "", "/"));

  it.each([
    ["moderation", "tab", "invites"],
    ["moderation", "tab", "channels"],
    ["strikes", "tab", "leave"],
    ["strikes", "tab", "settings"],
    ["todo", "tab", "raid"],
    ["todo", "tab", "cwl"],
    ["tickets", "status", "closed"],
    ["tickets", "type", "fwa"],
  ] as const)("%s ?%s=%s survives parse and serialize", (view, key, value) => {
    const path = dashboardPath({
      view,
      season: "",
      pageState: `${key}=${value}`,
    });
    const [pathname, search = ""] = path.split("?");
    expect(new URLSearchParams(search).get(key)).toBe(value);
    const route = dashboardTarget(`?${search}`, pathname);
    expect(route.view).toBe(view);
    expect(route.pageState).toBe(`${key}=${value}`);
    expect(parsePageParam(view, key, search)).toBe(value);
  });

  it("falls back to the default for unknown values", () => {
    expect(parsePageParam("moderation", "tab", "?tab=nope")).toBe("history");
    expect(parsePageParam("strikes", "tab", "?tab=replacements")).toBe(
      "history",
    );
    expect(parsePageParam("tickets", "status", "?status=x")).toBe("open");
    expect(parsePageParam("tickets", "type", "?type=")).toBe("all");
    expect(parsePageParam("todo", "tab", "?tab=nope")).toBe("");
    expect(pageParamQuery("tickets", "?status=x&type=main&other=1")).toBe(
      "type=main",
    );
  });

  it("keeps defaults and old URLs unchanged", () => {
    expect(dashboardPath({ view: "tickets", season: "" })).not.toContain("?");
    expect(
      dashboardPath({ view: "tickets", season: "", pageState: "status=open" }),
    ).not.toContain("status");
    expect(dashboardTarget("", "/server/tickets").pageState).toBeUndefined();
  });

  it("replaces the address without a new history entry", () => {
    const before = window.history.length;
    replacePageParam("tickets", "status", "denied");
    expect(window.location.search).toBe("?status=denied");
    expect(window.history.state).toEqual({ keep: 1 });
    replacePageParam("tickets", "status", "open");
    expect(window.location.search).toBe("");
    expect(window.history.length).toBe(before);
  });
});
