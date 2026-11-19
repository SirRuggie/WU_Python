import { expect, it } from "vitest";
import {
  managementPaths,
  managementTarget,
  townHallManagementPath,
} from "./managementLinks";
import { dashboardPath, dashboardTarget } from "./dashboardHistory";
import { dashboardViews } from "./SidebarNavigation";
import { loginPath } from "./memberLinks";

it("gives every dashboard view a unique clean page URL", () => {
  const paths = dashboardViews
    .filter((view) => !["member-activity", "member-timezones"].includes(view))
    .map((view) => dashboardPath({ view, season: "" }));
  expect(
    paths.every((path) => path.startsWith("/") && !path.includes("?")),
  ).toBe(true);
  expect(new Set(paths).size).toBe(dashboardViews.length - 2);
});

it("preserves all management destinations on refresh, old links and sign-in", () => {
  for (const [view, path] of Object.entries(managementPaths)) {
    const canonical =
      view === "member-activity"
        ? "moderation"
        : view === "member-timezones"
          ? "members-settings"
          : view;
    for (const pathname of [path, path + "/"]) {
      expect(dashboardTarget("?view=bonuses", pathname).view).toBe(canonical);
      expect(
        loginPath("?view=bonuses&season=123&step=announce", true, pathname),
      ).toBe(`/api/cwl/auth/discord?view=${canonical}&retry=1`);
    }
    const legacy = dashboardTarget(`?view=${view}&season=123`, "/");
    expect(dashboardPath(legacy)).toBe(
      view === "member-timezones" ? "/server/members" : path,
    );
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

it("retains strike filters and player through sign-in from canonical and legacy aliases", () => {
  for (const path of ["/replacements", "/clans/replacements"]) {
    const result = new URL(
      loginPath(
        "?clans=%23PYY&marked=1&sort=quiet&q=Aspen&tag=%23PQQ&next=https://evil.test",
        false,
        path,
      ),
      "https://fixture",
    );
    expect(result.searchParams.get("view")).toBe("replacements");
    expect(result.searchParams.get("clans")).toBe("#PYY");
    expect(result.searchParams.get("marked")).toBe("1");
    expect(result.searchParams.get("q")).toBe("Aspen");
    expect(result.searchParams.get("tag")).toBe("#PQQ");
    expect(result.searchParams.has("next")).toBe(false);
  }
});

it("canonicalizes old Members links and preserves the person through sign-in", () => {
  const id = "111111111111111111";
  expect(
    dashboardTarget(`?member=${id}`, "/server/member-timezones").view,
  ).toBe("members-settings");
  expect(managementTarget("?view=member-timezones", "/")).toBe(
    "members-settings",
  );
  expect(loginPath(`?member=${id}`, false, "/server/member-timezones")).toBe(
    `/api/cwl/auth/discord?view=members-settings&account=${id}`,
  );
  expect(
    loginPath("?member=https://evil.invalid", false, "/server/members"),
  ).toBe("/api/cwl/auth/discord?view=members-settings");
});

it("preserves exact Town Hall records through sign-in and canonicalizes legacy links", () => {
  for (const record of ["", "/settings", "/add", "/1", "/19", "/99"]) {
    const canonical = `/manage/town-halls${record}`;
    for (const path of [canonical, canonical + "/"]) {
      expect(townHallManagementPath(path)).toBe(canonical);
      expect(managementTarget("?view=access", path)).toBe("fwa-settings");
      const login = new URL(
        loginPath("?next=https://evil.test&town_hall=add", true, path),
        "https://fixture",
      );
      expect(Object.fromEntries(login.searchParams)).toEqual({
        view: "fwa-settings",
        town_hall: record.slice(1) || "list",
        retry: "1",
      });
    }
  }
  for (const [old, expected] of [
    ["/manage/operations/fwa_weight", "/manage/town-halls"],
    ["/manage/operations/fwa_weight/19", "/manage/town-halls/19"],
    ["/fwa_weight/19", "/manage/town-halls/19"],
  ]) {
    expect(townHallManagementPath(old)).toBe(expected);
    expect(townHallManagementPath(old + "/")).toBe(expected);
    expect(loginPath("", false, old)).toBe(loginPath("", false, expected));
  }
});

it("rejects malformed Town Hall editor paths and untrusted record query values", () => {
  for (const prefix of [
    "/manage/town-halls",
    "/manage/operations/fwa_weight",
    "/fwa_weight",
  ]) {
    for (const suffix of [
      "/0",
      "/01",
      "/100",
      "/-1",
      "/19/x",
      "/%31",
      "/19//",
      "/19?next=x",
      "/19#x",
      "/１９",
    ]) {
      const path = prefix + suffix;
      expect(townHallManagementPath(path)).toBeUndefined();
      expect(managementTarget("", path)).toBeUndefined();
      expect(loginPath("?town_hall=add", false, path)).toBe(
        "/api/cwl/auth/discord?view=home",
      );
    }
  }
  for (const path of [
    "//evil.test/manage/town-halls/19",
    "https://evil.test/manage/town-halls",
    "/manage/town-halls-extra",
    "/manage/town-halls//",
  ]) {
    expect(townHallManagementPath(path)).toBeUndefined();
  }
  expect(loginPath("?town_hall=add", false, "/server/fwa")).toBe(
    "/api/cwl/auth/discord?view=fwa-settings",
  );
});
