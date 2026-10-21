import { dashboardViews, type DashboardView } from "./SidebarNavigation";
export type DashboardRoute = { view: DashboardView; season: string; step?: "review" | "announce" };
export function dashboardTarget(search: string): DashboardRoute {
  const params = new URLSearchParams(search);
  const value =
    params.get("view") === "signups" ? "signup" : params.get("view");
  return {
    view: dashboardViews.includes(value as DashboardView)
      ? (value as DashboardView)
      : "home",
    ...(params.get("view") === "publication" && ["review", "announce"].includes(params.get("step") || "") ? { step: params.get("step") as "review" | "announce" } : {}),
    season: /^\d{1,18}$/.test(params.get("season") || "")
      ? params.get("season")!
      : "",
  };
}
export function dashboardPath(route: DashboardRoute) {
  const params = new URLSearchParams({ view: route.view });
  if (route.view === "publication" && route.step) params.set("step", route.step);
  if (route.season) params.set("season", route.season);
  return `/?${params}`;
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
    this.history[push ? "pushState" : "replaceState"](
      { wuDashboardIndex: this.index },
      "",
      dashboardPath(route),
    );
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
