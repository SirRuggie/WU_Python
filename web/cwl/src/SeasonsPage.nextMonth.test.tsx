// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import SeasonsPage from "./SeasonsPage";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (load) => ({ ...(await load<object>()), api }));
vi.mock("./CwlPoolRoles", () => ({ default: () => null }));
const button = (label: string, scope: ParentNode = document) =>
  Array.from(scope.querySelectorAll("button")).find(
    (b) => b.textContent === label,
  )!;
it("keeps Other name custom creation explicit and guards cancel and double confirmation", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const season = {
    id: 1,
    label: "November 2026",
    status: "draft",
    signup_open: false,
  };
  api.mockImplementation(async (_path: string, method?: string) =>
    method
      ? { id: 2, label: "Practice roster", copied_clan_count: 3 }
      : { seasons: [season], member_season: { season_id: null, revision: 4 } },
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const refresh = vi.fn(async () => {});
  const select = vi.fn();
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <SeasonsPage
            seasonId="1"
            seasons={[season]}
            memberSeason={{ season_id: null, revision: 4 }}
            onRefresh={refresh}
            onSeasonChange={select}
            onBusy={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    expect(button("Create December 2026", host)).toBeUndefined();
    const disclosure = host.querySelector("details")!;
    expect(disclosure.querySelector("summary")?.textContent).toBe("Other name");
    expect(disclosure.open).toBe(false);
    await act(async () => disclosure.querySelector("summary")!.click());
    const input = disclosure.querySelector("input")!;
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "Practice roster");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(button("Create season", disclosure).disabled).toBe(false);
    await act(async () => button("Create season", disclosure).click());
    expect(api.mock.calls.filter((c) => c[1])).toEqual([]);
    await act(async () =>
      button("Cancel", document.querySelector("dialog")!).click(),
    );
    expect(document.querySelector("dialog")).toBeNull();
    expect(api.mock.calls.filter((c) => c[1])).toEqual([]);
    await act(async () => button("Create season", disclosure).click());
    const confirm = button(
      "Create Practice roster",
      document.querySelector("dialog")!,
    );
    await act(async () => {
      confirm.click();
      confirm.click();
    });
    expect(api.mock.calls.filter((c) => c[1])).toEqual([
      ["/seasons", "POST", { label: "Practice roster", signup_open: false }],
    ]);
    expect(select).toHaveBeenCalledWith("2");
    expect(refresh).toHaveBeenCalledOnce();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
