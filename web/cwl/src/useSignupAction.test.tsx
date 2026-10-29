// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { DashboardPermissions } from "./DashboardPermissions";
import useSignupAction from "./useSignupAction";
import { ApiError, type Season } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
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
      if (method) throw new ApiError("409: changed by someone else", 409);
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

it("stale Fix closes without writes and reports the freshly visible season", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const season = {
    id: 2,
    label: "November",
    signup_open: true,
    status: "draft",
  };
  let visible = false;
  api.mockReset().mockImplementation(async () => ({
    seasons: [season],
    member_season: { season_id: visible ? 2 : 1, revision: 1 },
  }));
  const refresh = vi.fn(async () => {});
  function Harness() {
    const c = useSignupAction(season, refresh);
    return (
      <>
        <button onClick={() => void c.begin("fix")}>Fix</button>
        {c.dialog}
        <p>{c.notice}</p>
      </>
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <Harness />
        </DashboardPermissions.Provider>,
      ),
    );
    visible = true;
    await act(async () => host.querySelector("button")!.click());
    expect(host.querySelector('[role="dialog"]')).toBeNull();
    expect(host.textContent).toContain("Already visible to members.");
    expect(refresh).toHaveBeenCalledOnce();
    expect(api.mock.calls.filter((c) => c[1])).toHaveLength(0);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it("double-tapping Confirm dispatches one write even before React commits busy state", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const season = {
    id: 2,
    label: "November",
    signup_open: false,
    status: "draft",
  };
  const state = {
    seasons: [season],
    member_season: { season_id: 2, revision: 1 },
  };
  let finish!: () => void;
  api.mockReset().mockImplementation(async (_p, m) =>
    m
      ? new Promise<void>((r) => {
          finish = r;
        })
      : state,
  );
  function Harness() {
    const c = useSignupAction(season, async () => {});
    return (
      <>
        <button onClick={() => void c.begin("open")}>Begin</button>
        {c.dialog}
      </>
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <Harness />
        </DashboardPermissions.Provider>,
      ),
    );
    await act(async () => host.querySelector("button")!.click());
    const confirm = [...host.querySelectorAll("button")].find(
      (b) => b.textContent === "Confirm",
    )!;
    await act(async () => {
      confirm.click();
      confirm.click();
    });
    expect(api.mock.calls.filter((c) => c[1] === "PATCH")).toHaveLength(1);
    await act(async () => finish());
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it("a failed visibility read is discoverable and Retry performs only a read", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const season = {
    id: 2,
    label: "November",
    signup_open: true,
    status: "draft",
  };
  api
    .mockReset()
    .mockRejectedValueOnce(new Error("Offline"))
    .mockResolvedValue({
      seasons: [season],
      member_season: { season_id: 1, revision: 1 },
    });
  function Harness() {
    const c = useSignupAction(season, async () => {});
    return (
      <>
        {c.visibilityCheck}
        <p>{c.hiddenOpen ? "Hidden" : ""}</p>
      </>
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <Harness />
        </DashboardPermissions.Provider>,
      ),
    );
    expect(host.textContent).toContain("Couldn't check signup visibility");
    await act(async () => host.querySelector("button")!.click());
    expect(host.textContent).toBe("Hidden");
    expect(api.mock.calls).toEqual([["/seasons"], ["/seasons"]]);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
it("a lost open response displays uncertainty and refreshes without repeating the PATCH", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const season = {
    id: 2,
    label: "November",
    signup_open: false,
    status: "draft",
  };
  api.mockReset().mockImplementation(async (_p, m) => {
    if (m) throw new ApiError("Offline", 0);
    return { seasons: [season], member_season: { season_id: 2, revision: 1 } };
  });
  const refresh = vi.fn(async () => {});
  function Harness() {
    const c = useSignupAction(season, refresh);
    return (
      <>
        <button onClick={() => void c.begin("open")}>Begin</button>
        {c.dialog}
        <p>{c.error}</p>
      </>
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <Harness />
        </DashboardPermissions.Provider>,
      ),
    );
    await act(async () => host.querySelector("button")!.click());
    await act(async () =>
      [...host.querySelectorAll("button")]
        .find((b) => b.textContent === "Confirm")!
        .click(),
    );
    expect(host.textContent).toContain(
      "Signups may not have opened. Refreshing to check…",
    );
    expect(refresh).toHaveBeenCalledOnce();
    expect(api.mock.calls.filter((c) => c[0] === "/seasons")).toHaveLength(3);
    expect(api.mock.calls.filter((c) => c[1] === "PATCH")).toHaveLength(1);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
