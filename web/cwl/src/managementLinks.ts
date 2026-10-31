// Page destinations only; each API remains responsible for authorization.
export const managementPaths: Record<string, string> = {
  "staff-overview": "/staff",
  "clan-management": "/clans",
  strikes: "/strikes",
  replacements: "/replacements",
  "members-settings": "/server/members",
  "member-activity": "/server/moderation",
  moderation: "/server/moderation",
  "applications-settings": "/server/applications",
  "fwa-settings": "/server/fwa",
  "connections-settings": "/settings/integrations",
  "text-commands": "/server/commands",
  manage: "/server",
  "image-gallery": "/settings/image-gallery",
  tickets: "/tickets",
  access: "/settings/access",
  issues: "/settings/issues",
};

export function managementTarget(
  search: string,
  pathname: string,
): string | undefined {
  const path = pathname.replace(/\/$/, "");
  if (
    path === "/server/member-activity" ||
    (pathname === "/" &&
      new URLSearchParams(search).get("view") === "member-activity")
  )
    return "moderation";
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
