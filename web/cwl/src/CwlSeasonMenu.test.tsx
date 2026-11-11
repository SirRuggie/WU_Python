// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import ParticipationWorkspace from "./ParticipationWorkspace";
import BonusWorkspace from "./BonusWorkspace";
import ExportWorkspace from "./ExportWorkspace";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
const seasons = [
  { id: 1, label: "November 2026", status: "draft", signup_open: true },
  { id: 2, label: "December 2026", status: "archived", signup_open: false },
];
afterEach(() => {
  api.mockReset();
  localStorage.clear();
  sessionStorage.clear();
});
it.each(["Results", "Bonus", "Exports"])(
  "%s uses the shared season menu without a write or duplicate selection callback",
  async (kind) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
    };
    api.mockResolvedValue({
      accounts: [],
      clans: [],
      draws: [],
      history: [],
      policies: { main: 3, lazy: null },
      cycle: "2026-11",
      season_status: "draft",
      publication_version: 1,
      cycle_confirmed: [],
      active_other_cycles: [],
      sync: {
        enabled: false,
        cycle: "2026-11",
        cycle_source: "settings",
        status: "waiting",
        warning: null,
        last_checked_at: null,
        last_success_at: null,
        updated_at: null,
      },
      summary: {
        season_label: "November 2026",
        season_status: "draft",
        published_available: false,
      },
      columns: [],
      rows: [],
      counts: { rows: 0 },
    });
    const host = document.createElement("div"),
      root = createRoot(host),
      change = vi.fn();
    document.body.append(host);
    const Component =
      kind === "Results"
        ? ParticipationWorkspace
        : kind === "Bonus"
          ? BonusWorkspace
          : ExportWorkspace;
    try {
      await act(async () =>
        root.render(
          <Component seasonId="1" seasons={seasons} onSeasonChange={change} />,
        ),
      );
      // Results and Bonus medals use the short-list native select (prompt 228).
      const select = host.querySelector<HTMLSelectElement>(
        '.cwl-page-header select[name="season"]',
      );
      if (kind !== "Exports") {
        expect(select!.selectedOptions[0].textContent).toBe("November 2026");
        for (const value of ["1", "2"])
          await act(async () => {
            select!.value = value;
            select!.dispatchEvent(new Event("change", { bubbles: true }));
          });
        expect(change).toHaveBeenCalledExactlyOnceWith("2");
        expect(
          api.mock.calls.every((call) => !call[1] || call[1] === "GET"),
        ).toBe(true);
        return;
      }
      const trigger = host.querySelector<HTMLButtonElement>(
        ".cwl-page-header .roster-menu-trigger",
      )!;
      expect(trigger.textContent).toContain("November 2026");
      async function pick(label: string) {
        await act(async () => trigger.click());
        const item = [
          ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
        ].find((e) => e.textContent?.trim() === label)!;
        expect(item).toBeTruthy();
        await act(async () => {
          item.dispatchEvent(
            new MouseEvent("mousedown", { bubbles: true, button: 0 }),
          );
          item.dispatchEvent(
            new MouseEvent("mouseup", { bubbles: true, button: 0 }),
          );
          item.click();
        });
      }
      await pick("November 2026");
      expect(change).not.toHaveBeenCalled();
      await pick(
        kind === "Exports" ? "December 2026 · Archived" : "December 2026",
      );
      expect(change).toHaveBeenCalledExactlyOnceWith("2");
      expect(
        api.mock.calls.every((call) => !call[1] || call[1] === "GET"),
      ).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
