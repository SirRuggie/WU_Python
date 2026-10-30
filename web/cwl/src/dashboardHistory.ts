import { memberPaths, savedSignupTarget } from "./memberLinks";
import { dashboardViews, type DashboardView } from "./SidebarNavigation";
import { cwlPaths } from "./staffLinks";
import { managementPaths } from "./managementLinks";
const staffPaths: Record<string, string> = { ...cwlPaths, ...managementPaths, "weight-trial": "/clan-weights" };
const weightAliases = ["/weight", "/weights", "/weight-trial"];
export type DashboardRoute = { replacementClan?: string; view: DashboardView; season: string; signupPanel?: "register" | "saved"; step?: "review" | "announce"; activityFilter?: string; activityKind?: "war" | "cwl" };
export function dashboardTarget(search: string, pathname = '/'): DashboardRoute {
  pathname = pathname === '/' ? '/' : pathname.replace(/\/$/, '');
  const params = new URLSearchParams(search);
  const saved = savedSignupTarget(search, pathname);
  const pathView = Object.entries({...memberPaths, ...staffPaths}).find(([, path]) => path !== '/' && path === pathname)?.[0];
  const requested = (saved ? "signup" : undefined) || (weightAliases.includes(pathname) ? "weight-trial" : pathView) || (params.get("view") === "signups" ? "signup" : params.get("view"));
  const value = requested === "manage-signups" ? "roster" : requested;
  return {
    ...(saved ? {signupPanel: "saved" as const} : {}),
    view: dashboardViews.includes(value as DashboardView)
      ? (value as DashboardView)
      : "home",
    ...(value === "publication" && ["review", "announce"].includes(params.get("step") || "") ? { step: params.get("step") as "review" | "announce" } : {}),
    ...(value === "replacements" && /^#[0289PYLQGRJCUV]{3,15}$/.test(params.get("clan") || "") ? {replacementClan: params.get("clan")!} : {}),
    season: /^\d{1,18}$/.test(params.get("season") || "")
      ? params.get("season")!
      : "",
  };
}
export const seasonViews = new Set(['reminders', 'exports', 'declaration', 'publication', 'participation', 'bonuses', 'roster', 'staff']);
export function dashboardPath(route: DashboardRoute) {
  if (route.view === "signup" && route.signupPanel === "saved") return "/my-signups";
  if (memberPaths[route.view]) return memberPaths[route.view];
  const path = staffPaths[route.view];
  const params = new URLSearchParams(path ? {} : { view: route.view });
  if (route.view === "replacements" && /^#[0289PYLQGRJCUV]{3,15}$/.test(route.replacementClan || "")) params.set("clan", route.replacementClan!);
  if (route.view === "publication" && route.step) params.set("step", route.step);
  if (route.season && seasonViews.has(route.view)) params.set("season", route.season);
  return `${path || "/"}${params.size ? `?${params}` : ""}`;
}
type HistoryPort = Pick<History, "state" | "pushState" | "replaceState" | "go">;
// Index entries so canceling Back/Forward returns to the original entry without
// adding duplicate visits or destroying the forward stack.
export class DashboardHistory {
  private index: number;
  private restoring = false;
  constructor(private history: HistoryPort) {
    this.index = Number.isInteger(history.state?.wuDashboardIndex)
      ? history.state.wuDashboardIndex
      : 0;
    history.replaceState(
      { ...history.state, wuDashboardIndex: this.index },
      "",
    );
  }
  get pending() {
    return this.restoring;
  }
  write(route: DashboardRoute, push: boolean) {
    if (this.restoring) return;
    if (push) this.index++;
    const current =
      typeof window === "undefined"
        ? null
        : dashboardTarget(window.location.search, window.location.pathname);
    const samePage =
      !push && current?.view === route.view && current?.season === route.season;
    const url = new URL(dashboardPath(route), "https://dashboard.invalid");
    const account = samePage
      ? new URLSearchParams(window.location.search).get("account")
      : null;
    if (account) url.searchParams.set("account", account);
    const state = samePage ? { ...this.history.state } : {};
    this.history[push ? "pushState" : "replaceState"](
      {
        ...state,
        wuDashboardIndex: this.index,
        wuActivity: {
          view: route.view,
          filter: route.activityFilter || "",
          kind: route.activityKind,
        },
      },
      "",
      url.pathname + url.search,
    );
  }
  restoreTourEntry(state: unknown) {
    const target = (state as { wuDashboardIndex?: number } | null)
      ?.wuDashboardIndex;
    if (target === this.index) return;
    this.restoring = true;
    // A legacy same-document entry may have no index. Back still needs to
    // return forward once before the tour restores its saved URL.
    this.history.go(Number.isInteger(target) ? this.index - target! : 1);
  }
  pop(state: unknown, allow: () => boolean): boolean {
    const target = (state as { wuDashboardIndex?: number } | null)
      ?.wuDashboardIndex;
    if (this.restoring) {
      // Another Back/Forward click may already be queued while returning.
      if (Number.isInteger(target) && target !== this.index)
        this.history.go(this.index - target!);
      else this.restoring = false;
      return false;
    }
    if (!Number.isInteger(target)) return false;
    // Same-index entries are local overlays (for example an action panel), not a dashboard route visit.
    if (target === this.index) return false;
    if (!allow()) {
      if (this.index !== target) {
        this.restoring = true;
        this.history.go(this.index - target!);
      }
      return false;
    }
    this.index = target!;
    return true;
  }
}


export function activityContext(state: unknown, view: DashboardView): Pick<DashboardRoute, 'activityFilter' | 'activityKind'> {
  if (view !== 'todo' && view !== 'wars') return {}
  const value = (state as {wuActivity?: {view?: unknown; filter?: unknown; kind?: unknown}} | null)?.wuActivity
  if (!value || value.view !== view) return {}
  return {
    activityFilter: typeof value.filter === 'string' && /^#[A-Z0-9]{1,20}$/i.test(value.filter) ? value.filter : '',
    ...(value.kind === 'war' || value.kind === 'cwl' ? {activityKind: value.kind} : {}),
  }
}
