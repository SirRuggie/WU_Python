export const clanSections = [
  "Details",
  "Roles",
  "Channels",
  "Artwork",
  "War reminders",
] as const;
export type ClanSection = (typeof clanSections)[number];
export type ClanRoute = {
  tab: "clans" | "overview" | "history";
  tag?: string;
  section?: ClanSection;
};
const slugs = ["details", "roles", "channels", "artwork", "war-reminders"];
export function clanRoute(path: string): ClanRoute | undefined {
  const parts = path.replace(/\/$/, "").split("/").slice(1);
  if (parts[0] !== "clans") return;
  if (parts.length === 1) return { tab: "clans" };
  if (parts.length === 2 && ["reminders", "history"].includes(parts[1]))
    return { tab: parts[1] === "reminders" ? "overview" : "history" };
  let tag: string;
  try {
    tag = decodeURIComponent(parts[1]).toUpperCase();
  } catch {
    return;
  }
  if (!/^#[A-Z0-9]{3,15}$/.test(tag) || parts.length > 3) return;
  const index = parts[2] ? slugs.indexOf(parts[2]) : 0;
  if (index < 0) return;
  return { tab: "clans", tag, section: clanSections[index] };
}
export function clanPath(route: ClanRoute): string {
  if (route.tab === "overview") return "/clans/reminders";
  if (route.tab === "history") return "/clans/history";
  if (!route.tag || !/^#[A-Z0-9]{3,15}$/.test(route.tag)) return "/clans";
  const section = clanSections.indexOf(route.section || "Details");
  return (
    "/clans/" +
    encodeURIComponent(route.tag) +
    (section > 0 ? "/" + slugs[section] : "")
  );
}
