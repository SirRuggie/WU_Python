// Explicit page destinations; API permissions remain authoritative.
export const cwlPaths: Record<string, string> = {
  "manage-signups": "/cwl/signups",
  "roster": "/cwl/roster",
  "declaration": "/cwl/readiness",
  "reminders": "/cwl/reminders/signup",
  "cwl-returns": "/cwl/reminders/return",
  "publication": "/cwl/publish",
  "participation": "/cwl/results",
  "bonuses": "/cwl/bonuses",
  "exports": "/cwl/exports",
  "staff": "/cwl/settings",
};
export function cwlTarget(search: string, pathname: string): string | undefined {
  const path = pathname.replace(/\/$/, "");
  const target = Object.entries(cwlPaths).find(([, destination]) => destination === path)?.[0]
    || (pathname === "/" && Object.hasOwn(cwlPaths, new URLSearchParams(search).get("view") || "")
      ? new URLSearchParams(search).get("view")! : undefined);
  return target === "manage-signups" ? "roster" : target;
}
