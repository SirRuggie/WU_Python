// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./RosterHeader", () => ({ default: () => null }));
vi.mock("./SignupActivity", () => ({ default: () => null }));
it("rules saves use the real workspace path and never label the toast draft; errors belong only to that editor", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  HTMLElement.prototype.scrollIntoView = vi.fn();
  sessionStorage.setItem("wu-roster-1-mode", '"rules"');
  const clan = {
    tag: "#P2Y",
    name: "Amber Knights",
    pool: "main",
    capacity: 15,
    effective_capacity: 15,
    assigned_count: 0,
    min_weight: 150000,
    max_weight: null,
    archived: false,
  };
  const snapshot = {
    revision: 7,
    clans: [clan],
    accounts: [],
    metadata_updating: false,
  };
  let rejectSave = false;
  api.mockImplementation(async (_path: string, method?: string) => {
    if (method === "PATCH" && rejectSave)
      throw new Error("Only this save failed.");
    return snapshot;
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const button = (label: string) =>
    [...document.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
      item.textContent?.includes(label),
    )!;
  const change = async () =>
    act(async () => {
      const input = document.querySelector<HTMLInputElement>("input")!;
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "151");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <RosterWorkspace
            seasonId="1"
            seasons={
              [{ id: 1, label: "November 2026", status: "draft" }] as never
            }
            onSeasonChange={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    await act(async () => button("Amber Knights").click());
    await change();
    await act(async () => button("Save settings").click());
    expect(api).toHaveBeenCalledWith(
      "/seasons/1/lineup/%23P2Y/rules",
      "PATCH",
      {
        revision: 7,
        pool: "main",
        capacity: 15,
        min_weight: 151000,
        max_weight: null,
      },
    );
    const toast = host.querySelector('[role="status"]');
    expect(toast?.textContent).toContain(
      "Amber Knights placement rules saved.",
    );
    expect(toast?.textContent).not.toMatch(/Draft only|not published/i);
    rejectSave = true;
    await act(async () => button("Amber Knights").click());
    await change();
    await act(async () => button("Save settings").click());
    expect(document.querySelector("dialog")?.textContent).toContain(
      "Only this save failed.",
    );
    window.confirm = vi.fn().mockReturnValue(true);
    await act(async () =>
      document
        .querySelector<HTMLButtonElement>('[aria-label="Close panel"]')!
        .click(),
    );
    await act(async () => button("Amber Knights").click());
    expect(document.querySelector("dialog")?.textContent).not.toContain(
      "Only this save failed.",
    );
  } finally {
    act(() => root.unmount());
    host.remove();
    sessionStorage.clear();
    vi.restoreAllMocks();
  }
});
