// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import useSignupAction from "./useSignupAction";
import type { Season } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
vi.mock("./ConfirmDialog", () => ({
  default: ({ text, onConfirm, onCancel }: any) => (
    <div role="dialog">
      {text}
      <button onClick={onConfirm}>Confirm</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  ),
}));
for (const action of ["open", "fix"] as const)
  it(`${action} re-reads on open, refreshes on 409 and never retries`, async () => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const season = {
      id: 2,
      label: "November 2026",
      signup_open: action === "fix",
      status: "draft",
    } as Season;
    const fresh = {
      seasons: [season],
      member_season: { season_id: 1, revision: 4 },
    };
    api.mockReset().mockImplementation(async (_path, method) => {
      if (method) throw new Error("409: changed by someone else");
      return fresh;
    });
    const refresh = vi.fn(async () => {});
    function Harness() {
      const control = useSignupAction(season, refresh);
      return (
        <>
          <button onClick={() => void control.begin(action)}>Begin</button>
          <p>{control.error}</p>
          {control.dialog}
        </>
      );
    }
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: true, permissions: [] }}
          >
            <Harness />
          </DashboardPermissions.Provider>,
        ),
      );
      await act(async () =>
        (host.querySelector("button") as HTMLButtonElement).click(),
      );
      expect(
        api.mock.calls.filter((call) => call[0] === "/seasons"),
      ).toHaveLength(2);
      expect(host.textContent).toContain(
        action === "fix"
          ? "Show it to members?"
          : "Show it to members and open signups?",
      );
      await act(async () =>
        Array.from(host.querySelectorAll("button"))
          .find((button) => button.textContent === "Confirm")!
          .click(),
      );
      expect(host.textContent).toContain("409: changed by someone else");
      expect(refresh).toHaveBeenCalledTimes(1);
      expect(api.mock.calls.filter((call) => call[1])).toHaveLength(1);
      expect(
        api.mock.calls.filter((call) => call[0] === "/seasons"),
      ).toHaveLength(3);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  });
