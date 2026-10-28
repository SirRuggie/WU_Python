// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import WeightQueue from "./WeightQueue";
import RosterPlayerDialog from "./RosterPlayerDialog";
import type { RosterAccount } from "./roster";

const account = {
  tag: "#P2Y",
  player_name: "Managed",
  pool: "main",
  town_hall: 16,
  effective_weight: null,
  manual_weight: null,
  source_weight: null,
  source_status: "missing",
  clan_weight_managed: true,
  kept: false,
  assigned_clan_tag: null,
} as RosterAccount;
let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it.each(["queue", "details"])(
  "%s: permission-gated link uses guarded app navigation and no manual weight input",
  async (surface) => {
    const navigate = vi.fn();
    const render = async (permissions: string[]) =>
      act(async () =>
        root.render(
          <DashboardPermissions.Provider value={{ owner: false, permissions }}>
            {surface === "queue" ? (
              <WeightQueue
                accounts={[account]}
                busy={false}
                onEdit={() => {}}
                onSave={vi.fn()}
                onRefresh={() => {}}
                onClanWeights={navigate}
              />
            ) : (
              <RosterPlayerDialog
                account={account}
                clans={[]}
                busy={false}
                onClose={() => {}}
                onSave={vi.fn()}
                onRemove={vi.fn()}
                onClanWeights={navigate}
              />
            )}
          </DashboardPermissions.Provider>,
        ),
      );
    await render(["cwl_roster", "clan_weights"]);
    const link = document.querySelector<HTMLAnchorElement>(
      'a[href="/clan-weights"]',
    )!;
    expect(link.textContent).toBe("Open Clan weights →");
    const click = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
    });
    await act(async () => {
      link.dispatchEvent(click);
    });
    expect(click.defaultPrevented).toBe(true);
    expect(navigate).toHaveBeenCalledOnce();
    expect(
      document.querySelector(".compact-weight-controls, .manual-weight-fields"),
    ).toBeNull();
    if (surface === "queue")
      expect(
        host.querySelector(
          '.weight-queue-row input, .weight-queue-row button[type="submit"]',
        ),
      ).toBeNull();
    await render(["cwl_roster"]);
    expect(document.querySelector('a[href="/clan-weights"]')).toBeNull();
    expect(document.body.textContent).toContain(
      "Weight comes from Clan weights. Ask a staff member with Clan weights access.",
    );
  },
);
