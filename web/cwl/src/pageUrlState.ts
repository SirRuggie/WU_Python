import type { DashboardView } from "./SidebarNavigation";

type ParamSpec = { values: readonly string[]; fallback: string };

/**
 * Page tabs and main filters kept in the address. Defaults stay out of the URL,
 * so every link that exists today keeps its short form and its meaning.
 */
export const pageParamSpecs: Partial<
  Record<DashboardView, Record<string, ParamSpec>>
> = {
  moderation: {
    tab: { values: ["history", "invites", "channels"], fallback: "history" },
  },
  strikes: {
    tab: { values: ["history", "leave", "settings"], fallback: "history" },
  },
  todo: {
    tab: {
      values: ["war", "cwl", "raid", "games", "private"],
      fallback: "",
    },
  },
  tickets: {
    status: {
      values: ["open", "all", "approved", "denied", "closed"],
      fallback: "open",
    },
    type: { values: ["all", "main", "fwa"], fallback: "all" },
  },
};

/** One value; an unknown or missing value gives the fallback. */
export function parsePageParam(
  view: DashboardView,
  key: string,
  search: string,
): string {
  const spec = pageParamSpecs[view]?.[key];
  if (!spec) return "";
  const value = new URLSearchParams(search).get(key) || "";
  return spec.values.includes(value) ? value : spec.fallback;
}

/** Query string with only the known, non-default params of this page. */
export function pageParamQuery(view: DashboardView, search: string): string {
  const params = new URLSearchParams();
  for (const [key, spec] of Object.entries(pageParamSpecs[view] || {})) {
    const value = parsePageParam(view, key, search);
    if (value && value !== spec.fallback) params.set(key, value);
  }
  return params.toString();
}

/** Replaces the current entry's param so Back keeps leaving the page, not the tab. */
export function replacePageParam(
  view: DashboardView,
  key: string,
  value: string,
) {
  const spec = pageParamSpecs[view]?.[key];
  if (!spec || typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (value && value !== spec.fallback && spec.values.includes(value))
    url.searchParams.set(key, value);
  else url.searchParams.delete(key);
  window.history.replaceState(
    window.history.state,
    "",
    url.pathname + url.search + url.hash,
  );
}
