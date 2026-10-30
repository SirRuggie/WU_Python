import { expect, it } from "vitest";
import { managementPaths, managementTarget } from "./managementLinks";
import { dashboardPath, dashboardTarget } from "./dashboardHistory";
import { dashboardViews } from "./SidebarNavigation";
import { loginPath } from "./memberLinks";

it("gives every dashboard view a unique clean page URL", () => {
  const paths = dashboardViews
    .filter((view) => view !== "member-activity")
    .map((view) => dashboardPath({ view, season: "" }));
  expect(
    paths.every((path) => path.startsWith("/") && !path.includes("?")),
  ).toBe(true);
  expect(new Set(paths).size).toBe(dashboardViews.length - 1);
});

it("preserves all management destinations on refresh, old links and sign-in", () => {
  for (const [view, path] of Object.entries(managementPaths)) {
    const canonical = view === "member-activity" ? "moderation" : view;
    for (const pathname of [path, path + "/"]) {
      expect(dashboardTarget("?view=bonuses", pathname).view).toBe(canonical);
      expect(
        loginPath("?view=bonuses&season=123&step=announce", true, pathname),
      ).toBe(`/api/cwl/auth/discord?view=${canonical}&retry=1`);
    }
    const legacy = dashboardTarget(`?view=${view}&season=123`, "/");
    expect(dashboardPath(legacy)).toBe(path);
    expect(loginPath(`?view=${view}`, false, "/")).toBe(
      `/api/cwl/auth/discord?view=${canonical}`,
    );
  }
});

it("does not accept external or lookalike management destinations", () => {
  for (const path of [
    "//evil.test/settings/access",
    "https://evil.test",
    "/settings/access/extra",
    "/settings/%61ccess",
  ]) {
    expect(managementTarget("", path)).toBeUndefined();
    expect(loginPath("", false, path)).toBe("/api/cwl/auth/discord?view=home");
  }
  expect(managementTarget("?view=access", "/tasks")).toBeUndefined();
  expect(managementTarget("?view=__proto__", "/")).toBeUndefined();
});

it("canonicalizes old member activity links to the permission-gated Moderation route", () => {
  expect(dashboardTarget("", "/server/member-activity").view).toBe(
    "moderation",
  );
  expect(dashboardTarget("", "/server/moderation").view).toBe("moderation");
  expect(dashboardPath({ view: "member-activity", season: "" })).toBe(
    "/server/moderation",
  );
  expect(dashboardPath({ view: "moderation", season: "" })).toBe(
    "/server/moderation",
  );
});
