// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
import type { SignupChange } from "./signupActivityModel";
const state = vi.hoisted(() => ({
  api: vi.fn(),
  fill: null as null | ((item: SignupChange) => boolean),
  dirty: null as null | ((value: boolean) => void),
  busy: null as null | ((value: boolean) => void),
}));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));
vi.mock("./RosterHeader", () => ({
  default: (props: { onFillSignupSpot: typeof state.fill }) => {
    state.fill = props.onFillSignupSpot;
    return null;
  },
}));
vi.mock("./ClanSettings", () => ({
  default: (props: {
    onDirty: typeof state.dirty;
    onHostingBusy: typeof state.busy;
  }) => {
    state.dirty = props.onDirty;
    state.busy = props.onHostingBusy;
    return null;
  },
}));
vi.mock("./CompareClans", () => ({
  default: () => <div>Compare destination</div>,
}));
it.each(["prepend", "null", "full", "dirty", "busy", "default", "stale"])(
  "Fill spot respects workspace state: %s",
  async (scenario) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    sessionStorage.clear();
    localStorage.clear();
    sessionStorage.setItem("wu-roster-1-mode", '"rules"');
    const saved =
      scenario === "full"
        ? Array.from({ length: 10 }, (_, i) => `#CLAN${i}`)
        : scenario === "stale"
          ? [
              "#STALE",
              "#ARCHIVED",
              ...Array.from({ length: 8 }, (_, i) => `#CLAN${i}`),
            ]
          : ["#Q2Y", "#P2Y", "#G2Y"];
    const key = "wu-compare-clans:1:main";
    if (scenario !== "default")
      localStorage.setItem(key, JSON.stringify(saved));
    localStorage.setItem("wu-compare-clans:1:lazy", '["#LAZY"]');
    state.api.mockResolvedValue({
      revision: 1,
      accounts: [],
      clans: [
        ...Array.from({ length: 10 }, (_, i) => ({
          tag: `#CLAN${i}`,
          name: `Available ${i}`,
          pool: "main",
          archived: false,
        })),
        ...["#P2Y", "#Q2Y", "#G2Y"].map((tag) => ({
          tag,
          name: `Z ${tag}`,
          pool: "main",
          archived: false,
        })),
        { tag: "#ARCHIVED", name: "A archived", pool: "main", archived: true },
        { tag: "#LAZY", name: "A other pool", pool: "lazy", archived: false },
      ],
      metadata_updating: false,
    });
    const confirm = vi.fn(() => false);
    window.confirm = confirm;
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: true, permissions: [] }}
          >
            <RosterWorkspace
              seasonId="1"
              seasons={[]}
              onSeasonChange={() => {}}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      if (scenario === "dirty") await act(async () => state.dirty!(true));
      if (scenario === "busy") await act(async () => state.busy!(true));
      let accepted = false;
      await act(async () => {
        accepted = state.fill!({
          from_pool: "main",
          assigned_clan_tag: scenario === "null" ? null : "#P2Y",
        } as SignupChange);
      });
      const blocked = scenario === "dirty" || scenario === "busy";
      expect(accepted).toBe(!blocked);
      expect(host.textContent?.includes("Compare destination")).toBe(!blocked);
      expect(JSON.parse(localStorage.getItem(key)!)).toEqual(
        scenario === "default"
          ? ["#P2Y", "#CLAN0", "#CLAN1", "#CLAN2", "#CLAN3"]
          : scenario === "stale"
            ? ["#P2Y", ...saved.slice(2)]
            : blocked || scenario === "null"
              ? saved
              : ["#P2Y", ...saved.filter((tag) => tag !== "#P2Y")].slice(0, 10),
      );
      expect(localStorage.getItem("wu-compare-clans:1:lazy")).toBe('["#LAZY"]');
      if (scenario === "dirty") expect(confirm).toHaveBeenCalledOnce();
      expect(
        state.api.mock.calls.every((call) => !call[1] || call[1] === "GET"),
      ).toBe(true);
    } finally {
      await act(async () => root.unmount());
      host.remove();
      sessionStorage.clear();
      localStorage.clear();
      vi.restoreAllMocks();
      state.api.mockReset();
    }
  },
);
