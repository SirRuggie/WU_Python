// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import ParticipationWorkspace from "./ParticipationWorkspace";
import BonusWorkspace from "./BonusWorkspace";

const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({ useDashboardPermission: () => true }));
const failure = "Some Clash CWL data could not be refreshed; cached results are marked stale";
afterEach(() => {
  api.mockReset();
  localStorage.clear();
  sessionStorage.clear();
  document.body.replaceChildren();
});

it.each(["participation", "bonus"] as const)(
  "%s keeps an older scoped failure visible without duplicating fresh warnings or borrowing hidden failures",
  async (page) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const account = {
      tag: "#P2Y", player_name: "Saved player", town_hall: 16, pool: "main",
      assigned_clan_tag: "#A", assigned_clan_name: "Alpha", attacks: 2, stars: 5,
      source_attacks: 2, source_stars: 5, source_status: "stale", source_complete: false,
      notes: "", revision: 0, updated_by: null, updated_at: null, in_latest_publication: true,
    };
    const oldStatus = { code: "not_recent", label: "Results need a check",
      warning: "These results have not been checked recently.", failed_clan: false,
      round: null, last_check_failed: true };
    try {
      for (const scenario of ["old", "fresh", "hidden"] as const) {
        const display_status = scenario === "old" ? oldStatus : scenario === "fresh"
          ? { code: "stale", label: "Last saved results", warning: "This clan could not refresh. Showing its last saved results.", failed_clan: true, round: null }
          : { code: "complete", label: "Complete", warning: null, failed_clan: false, round: null };
        api.mockResolvedValue({
          season_status: "draft", cycle: "2026-11", revision: 0, publication_version: 1,
          policies: { main: 3, lazy: null }, policy: {}, clans: [{ tag: "#A", name: "Alpha", slots: 1 }],
          accounts: [{ ...account, display_status }], draws: [], history: [], cycle_confirmed: [], active_other_cycles: [],
          sync: { cycle: "2026-11", cycle_source: "settings", enabled: false, status: "stale",
            warning: failure, last_checked_at: "2026-11-01T12:00:00Z", last_success_at: null, updated_at: null },
        });
        const Component = page === "bonus" ? BonusWorkspace : ParticipationWorkspace;
        await act(async () => root.render(<Component key={scenario} seasonId="1"
          seasons={[{ id: 1, label: "November 2026", status: "draft", signup_open: true }]}
          onSeasonChange={() => {}} />));
        const text = host.textContent || "";
        if (scenario === "old") expect(text.split(failure)).toHaveLength(2);
        else expect(text).not.toContain(failure);
        if (scenario === "fresh") {
          expect(text).toContain("1 clan could not refresh: Alpha. Showing last saved results for 1 account in this view.");
        }
        expect(api.mock.calls.every(call => !call[1] || call[1] === "GET")).toBe(true);
      }
    } finally {
      await act(async () => root.unmount());
    }
  },
);
