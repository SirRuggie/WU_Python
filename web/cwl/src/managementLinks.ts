// Page destinations only; each API remains responsible for authorization.
export const managementPaths: Record<string, string> = {
  "staff-overview": "/staff",
  "clan-management": "/clans",
  strikes: "/strikes",
  replacements: "/replacements",
  "member-timezones": "/server/member-timezones",
  "members-settings": "/server/members",
  "member-activity": "/server/moderation",
  moderation: "/server/moderation",
  "applications-settings": "/server/applications",
  "fwa-settings": "/server/fwa",
  "connections-settings": "/settings/integrations",
  "text-commands": "/server/commands",
  manage: "/server",
  "image-gallery": "/settings/image-gallery",
  "world-clocks": "/settings/world-clocks",
  tickets: "/tickets",
  access: "/settings/access",
  issues: "/settings/issues",
};

/** Canonical page path only; API authorization is unchanged. */
export function townHallManagementPath(pathname: string): string | undefined {
  const path = pathname.replace(/\/$/, "");
  const current = path.match(
    /^\/manage\/town-halls(?:\/(settings|add|[1-9][0-9]?))?$/,
  );
  if (current) return `/manage/town-halls${current[1] ? `/${current[1]}` : ""}`;
  const legacy =
    path.match(/^\/manage\/operations\/fwa_weight(?:\/([1-9][0-9]?))?$/) ||
    path.match(/^\/fwa_weight\/([1-9][0-9]?)$/);
  return legacy
    ? `/manage/town-halls${legacy[1] ? `/${legacy[1]}` : ""}`
    : undefined;
}

export function managementTarget(
  search: string,
  pathname: string,
): string | undefined {
  const path = pathname.replace(/\/$/, "");
  if (townHallManagementPath(pathname)) return "fwa-settings";
  if (
    path === "/server/member-activity" ||
    (pathname === "/" &&
      new URLSearchParams(search).get("view") === "member-activity")
  )
    return "moderation";
  if (
    path === "/server/member-timezones" ||
    (pathname === "/" &&
      new URLSearchParams(search).get("view") === "member-timezones")
  )
    return "members-settings";
  if (path === "/server/moderation") return "moderation";
  if (path === "/clans/strikes") return "strikes";
  if (path === "/clans/replacements") return "replacements";
  const matched = Object.entries(managementPaths).find(
    ([, destination]) => destination === path,
  )?.[0];
  const legacy = new URLSearchParams(search).get("view") || "";
  return (
    matched ||
    (pathname === "/" && Object.hasOwn(managementPaths, legacy)
      ? legacy
      : undefined)
  );
}
