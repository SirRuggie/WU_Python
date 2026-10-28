// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import StaffSignupControls from "./StaffSignupControls";
import SeasonsPage from "./SeasonsPage";
import { DashboardPermissions } from "./DashboardPermissions";
const { retry } = vi.hoisted(() => ({ retry: vi.fn() }));
vi.mock("./useSignupAction", () => ({
  default: () => ({
    busy: false,
    error: "",
    notice: "",
    hiddenOpen: false,
    dialog: null,
    begin: vi.fn(),
    visibilityCheck: (
      <p>
        Couldn't check signup visibility ·{" "}
        <button onClick={retry}>Retry</button>
      </p>
    ),
  }),
}));
vi.mock("./MemberSeasonSettings", () => ({ default: () => null }));
it.each(["staff", "seasons"])(
  "%s exposes the failed visibility read and functional Retry",
  async (consumer) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    retry.mockClear();
    const season = {
      id: 1,
      label: "November",
      status: "draft",
      signup_open: true,
    };
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: true, permissions: [] }}
          >
            {consumer === "staff" ? (
              <StaffSignupControls
                season={season}
                onChanged={async () => {}}
                onDirty={() => {}}
                onBusy={() => {}}
              />
            ) : (
              <SeasonsPage
                userId="1"
                seasonId="1"
                seasons={[season]}
                memberSeason={{ season_id: 1, revision: 1 }}
                onSeasonChange={() => {}}
                onRefresh={async () => {}}
                onClans={() => {}}
                onBusy={() => {}}
              />
            )}
          </DashboardPermissions.Provider>,
        ),
      );
      expect(host.textContent).toContain("Couldn't check signup visibility");
      const button = [...host.querySelectorAll("button")].find(
        (b) => b.textContent === "Retry",
      )!;
      expect(button).toBeDefined();
      await act(async () => button.click());
      expect(retry).toHaveBeenCalledOnce();
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
