// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { resultsPageMode } from "./ResultsBonusesWorkspace";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
// The two views show which one the page chose and what it was given.
vi.mock("./ParticipationWorkspace", () => ({
  default: ({
    urlState,
    onBonus,
    onDirty,
  }: {
    urlState?: string;
    onBonus?: (state?: string) => void;
    onDirty?: (value: boolean) => void;
  }) => (
    <section data-testid="list">
      <h1>List view</h1>
      <p data-testid="list-state">{urlState}</p>
      <button onClick={() => onDirty?.(true)}>Hold list edit</button>
      {onBonus ? (
        <button onClick={() => onBonus("pool=lazy&clan=%232YQ&step=draw")}>
          Open steps
        </button>
      ) : (
        <p>No steps</p>
      )}
    </section>
  ),
}));
vi.mock("./BonusWorkspace", () => ({
  default: ({
    urlState,
    onResults,
  }: {
    urlState?: string;
    onResults?: (state?: string) => void;
  }) => (
    <section data-testid="steps">
      <h1>Steps view</h1>
      <p data-testid="steps-state">{urlState}</p>
      {onResults ? (
        <button
          onClick={() => onResults("pool=lazy&clan=%232YQ&outcome=partial")}
        >
          Open list
        </button>
      ) : (
        <p>No list</p>
      )}
    </section>
  ),
}));
vi.mock("./ExportWorkspace", () => ({
  default: () => <h1>Exports fixture</h1>,
}));
let cleanup: (() => Promise<void>) | undefined;
afterEach(async () => {
  await cleanup?.();
  cleanup = undefined;
  vi.restoreAllMocks();
  api.mockReset();
  sessionStorage.clear();
  localStorage.clear();
});
async function mount(path: string, permissions: string[]) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  history.replaceState({}, "", path);
  sessionStorage.clear();
  localStorage.clear();
  api.mockImplementation(async (route: string) =>
    route === "/auth/me"
      ? {
          authenticated: true,
          user: { id: "123456789012345678", username: "Staff" },
          is_owner: false,
          can_edit: true,
          csrf_token: "fixture",
          dashboard_permissions: permissions,
        }
      : route === "/seasons"
        ? {
            seasons: [
              { id: 1, label: "November", status: "draft", signup_open: true },
            ],
            member_season: { season_id: 1, revision: 1 },
          }
        : route === "/config"
          ? { dev_fixture: true }
          : {},
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  cleanup = async () => {
    await act(async () => root.unmount());
    host.remove();
  };
  const settle = async () => {
    for (let i = 0; i < 5; i++)
      await act(async () => {
        await new Promise((resolve) => setTimeout(resolve, 10));
      });
  };
  await act(async () => root.render(<App />));
  await settle();
  const button = (label: string, selector = "button, a") =>
    [...host.querySelectorAll<HTMLButtonElement>(selector)].find(
      (node) => node.textContent?.trim() === label,
    );
  const text = (id: string) =>
    host.querySelector(`[data-testid="${id}"]`)?.textContent;
  return { host, settle, button, text };
}
const both = ["cwl_results", "cwl_bonuses"];

describe("one page for two addresses", () => {
  it("/cwl/results opens the player list with its state", async () => {
    const { host, text } = await mount("/cwl/results?season=1&pool=lazy", both);
    expect(host.querySelector(".topbar strong")?.textContent).toBe(
      "Results & bonuses",
    );
    expect(text("list-state")).toBe("pool=lazy");
    expect(host.querySelector('[data-testid="steps"]')).toBeNull();
  });
  it("/cwl/bonuses?...&clan&step opens that clan's steps, not a second page", async () => {
    const { host, text } = await mount(
      "/cwl/bonuses?season=1&pool=lazy&clan=%232YQ&step=draw",
      both,
    );
    expect(host.querySelector(".topbar strong")?.textContent).toBe(
      "Results & bonuses",
    );
    expect(text("steps-state")).toBe("pool=lazy&clan=%232YQ&step=draw");
    expect(host.querySelector('[data-testid="list"]')).toBeNull();
  });
  it("has no in-page tab bar and ends with a Next link to Exports", async () => {
    const { host } = await mount("/cwl/results?season=1", [
      ...both,
      "cwl_send",
    ]);
    expect(host.querySelector('[aria-label="Results sections"]')).toBeNull();
    const next = host.querySelector<HTMLButtonElement>(".cwl-next-cue");
    expect(next?.textContent).toBe("Next: Exports & history ›");
    await act(async () => next!.click());
    expect(location.pathname).toBe("/cwl/exports");
    const sidebar = [...host.querySelectorAll(".sidebar a")].map((node) =>
      node.textContent?.trim(),
    );
    expect(sidebar).toContain("Results & bonuses");
    expect(sidebar).not.toContain("Bonus medals");
    expect(sidebar).not.toContain("Results & participation");
  });
  it("moves between the list and a clan's steps and keeps the address in sync", async () => {
    const { host, button, text, settle } = await mount(
      "/cwl/results?season=1&pool=lazy",
      both,
    );
    await act(async () => button("Open steps")!.click());
    await settle();
    expect(text("steps-state")).toBe("pool=lazy&clan=%232YQ&step=draw");
    expect(location.pathname).toBe("/cwl/results");
    expect(location.search).toContain("clan=%232YQ&step=draw");
    await act(async () => button("Open list")!.click());
    await settle();
    expect(text("list-state")).toBe("pool=lazy&clan=%232YQ&outcome=partial");
    expect(host.querySelector('[data-testid="steps"]')).toBeNull();
  });
  it("Back returns to the list; the address Forward restores names the steps view", async () => {
    const { host, button, text, settle } = await mount(
      "/cwl/results?season=1&pool=lazy",
      both,
    );
    await act(async () => button("Open steps")!.click());
    await settle();
    expect(text("steps-state")).toBe("pool=lazy&clan=%232YQ&step=draw");
    await act(async () => history.back());
    await settle();
    expect(text("list-state")).toBe("pool=lazy");
    expect(host.querySelector('[data-testid="steps"]')).toBeNull();
    // happy-dom has no forward entry, so the address Forward restores is checked directly.
    const grants = { results: true, bonuses: true };
    expect(
      resultsPageMode("pool=lazy&clan=%232YQ&step=draw", "list", grants),
    ).toBe("steps");
    // Every steps entry carries a step or the steps marker, so Forward never lands on the list.
    expect(
      resultsPageMode("pool=lazy&clan=%232YQ&step=approve", "list", grants),
    ).toBe("steps");
    expect(
      resultsPageMode("pool=lazy&clan=%232YQ&open=steps", "list", grants),
    ).toBe("steps");
    // An old address with neither keeps the view the page is in.
    expect(resultsPageMode("pool=lazy&clan=%232YQ", "list", grants)).toBe(
      "list",
    );
  });
  it("guards leaving the page while the list has unsaved work", async () => {
    const { button, settle } = await mount("/cwl/results?season=1", both);
    await act(async () => button("Hold list edit")!.click());
    await act(async () => button("Exports & history", ".sidebar a")!.click());
    await settle();
    expect(document.querySelectorAll(".confirm-dialog")).toHaveLength(1);
    expect(location.pathname).toBe("/cwl/results");
  });
});

describe("grants", () => {
  it("results only: the list, no steps, and a clan address stays on the list", async () => {
    const { host, text } = await mount(
      "/cwl/bonuses?season=1&pool=lazy&clan=%232YQ&step=draw",
      ["cwl_results"],
    );
    expect(text("list-state")).toBe("pool=lazy&clan=%232YQ&step=draw");
    expect(host.textContent).toContain("No steps");
    expect(host.querySelector('[data-testid="steps"]')).toBeNull();
  });
  it("bonus only: the steps view, no list, even with no clan", async () => {
    const { host, text } = await mount("/cwl/results?season=1&pool=lazy", [
      "cwl_bonuses",
    ]);
    expect(text("steps-state")).toBe("pool=lazy");
    expect(host.textContent).toContain("No list");
    expect(host.querySelector('[data-testid="list"]')).toBeNull();
    expect(
      [...host.querySelectorAll(".sidebar a")].map((node) =>
        node.textContent?.trim(),
      ),
    ).toContain("Results & bonuses");
  });
  it("cwl_send alone reaches the bonus half", async () => {
    const { host } = await mount("/cwl/results?season=1", ["cwl_send"]);
    expect(host.querySelector('[data-testid="steps"]')).not.toBeNull();
  });
  it("both: the list offers the steps and the steps offer the list", async () => {
    const { host } = await mount("/cwl/results?season=1", both);
    expect(host.textContent).toContain("Open steps");
  });
  it("neither: the page is not offered", async () => {
    const { host, settle } = await mount("/cwl/results?season=1", [
      "cwl_roster",
    ]);
    // The access check sends the user home once Home has loaded.
    for (let i = 0; i < 40 && host.querySelector('[data-testid="list"]'); i++)
      await settle();
    expect(host.querySelector('[data-testid="list"]')).toBeNull();
    expect(host.querySelector('[data-testid="steps"]')).toBeNull();
    expect(
      [...host.querySelectorAll(".sidebar a")].map((node) =>
        node.textContent?.trim(),
      ),
    ).not.toContain("Results & bonuses");
  });
});

describe("resultsPageMode", () => {
  const all = { results: true, bonuses: true };
  it("picks the view from grants first, then the address", () => {
    expect(
      resultsPageMode("clan=%232YQ", null, { results: true, bonuses: false }),
    ).toBe("list");
    expect(resultsPageMode("", null, { results: false, bonuses: true })).toBe(
      "steps",
    );
    expect(resultsPageMode("pool=lazy", null, all)).toBe("list");
    expect(resultsPageMode("clan=%232YQ", null, all)).toBe("steps");
    expect(resultsPageMode("clan=%232YQ&step=draw", "list", all)).toBe("steps");
    expect(resultsPageMode("clan=%232YQ&outcome=partial", null, all)).toBe(
      "list",
    );
  });
  it("keeps the current view for a clan without a step", () => {
    expect(resultsPageMode("clan=%232YQ", "list", all)).toBe("list");
    expect(resultsPageMode("clan=%232YQ", "steps", all)).toBe("steps");
    expect(resultsPageMode("", "steps", all)).toBe("list");
  });
});
