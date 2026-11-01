// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({
  api: vi.fn(),
  open: null as null | ((tag: string) => boolean),
}));
vi.mock("./api", async (orig) => ({
  ...(await orig<object>()),
  api: state.api,
}));
vi.mock("./RosterHeader", () => ({
  default: (props: { onSignupDetails: (tag: string) => boolean }) => {
    state.open = props.onSignupDetails;
    return null;
  },
}));
vi.mock("./RosterPlayerDialog", () => ({
  default: ({
    onFillerChanged,
  }: {
    onFillerChanged: (saved?: unknown) => Promise<void>;
  }) => (
    <button onClick={() => void onFillerChanged()}>
      Simulate revoked filler save
    </button>
  ),
}));
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
it("permission failure from the filler editor never produces a saved-success toast", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  sessionStorage.clear();
  sessionStorage.setItem("wu-roster-1-mode", '"rules"');
  state.api.mockResolvedValue({
    revision: 1,
    undo: null,
    clans: [],
    accounts: [
      {
        tag: "#P2Y",
        player_name: "Player",
        user_id: "",
        pool: "main",
        town_hall: 16,
        source_status: "current",
        source_weight: 100000,
        effective_weight: 100000,
        manual_weight: null,
        assigned_clan_tag: null,
        kept: false,
      },
    ],
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <RosterWorkspace
            seasonId="1"
            seasons={[]}
            onSeasonChange={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    await act(async () => {
      state.open!("#P2Y");
    });
    const button = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "Simulate revoked filler save",
    );
    expect(button).toBeTruthy();
    await act(async () => button!.click());
    expect(host.textContent).not.toContain("Filler mark saved.");
    expect(host.textContent).toContain("Your roster access changed");
    expect(host.querySelector(".is-success")).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
