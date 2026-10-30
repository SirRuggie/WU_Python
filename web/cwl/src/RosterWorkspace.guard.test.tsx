// @vitest-environment happy-dom
import { act, useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import RosterWorkspace from "./RosterWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";

const state = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: state.api,
}));
vi.mock("./RosterHeader", () => ({
  default: ({
    onSeasonChange,
    onCapacitySettings,
  }: {
    onSeasonChange: (id: string) => void;
    onCapacitySettings: (tag: string) => void;
  }) => (
    <>
      <button onClick={() => onSeasonChange("2")}>Next season</button>
      <button onClick={() => onCapacitySettings("#FUN")}>Set capacity</button>
    </>
  ),
}));
vi.mock("./WeightQueue", () => ({
  default: ({
    onDirty,
    onDirtyCount,
    resetToken,
  }: {
    onDirty: (dirty: boolean) => void;
    onDirtyCount: (count: number) => void;
    resetToken: number;
  }) => {
    const [draft, setDraft] = useState("");
    useEffect(() => {
      setDraft("");
    }, [resetToken]);
    useEffect(() => {
      onDirty(!!draft);
      onDirtyCount(draft ? 1 : 0);
    }, [draft, onDirty, onDirtyCount]);
    return (
      <input
        aria-label="Weight draft"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
      />
    );
  },
}));
vi.mock("./StaffSignupControls", () => ({ default: () => null }));
vi.mock("./SignupActivity", () => ({ default: () => null }));
vi.mock("./CompareClans", () => ({ default: () => <p>Comparison opened</p> }));
vi.mock("./ClanSettings", () => ({
  default: ({
    onDirty,
    onHostingBusy,
  }: {
    onDirty: (dirty: boolean) => void;
    onHostingBusy: (busy: boolean) => void;
  }) => (
    <>
      <button onClick={() => onDirty(true)}>Edit clan setting</button>
      <button onClick={() => onHostingBusy(true)}>Begin save</button>
    </>
  ),
}));

afterEach(() => {
  state.api.mockReset();
  sessionStorage.clear();
  localStorage.clear();
  vi.restoreAllMocks();
});

it.each(["tab", "season", "capacity"])(
  "keeps a weight draft until %s navigation is discarded",
  async (destination) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    sessionStorage.setItem("wu-roster-1-mode", '"weights"');
    state.api.mockResolvedValue({
      revision: 1,
      accounts: [],
      clans: [{ tag: "#FUN", name: "Funnies", pool: "main", archived: false }],
      metadata_updating: false,
    });
    const confirm = vi.fn(() => false);
    window.confirm = confirm;
    HTMLDialogElement.prototype.showModal = function () {
      this.open = true;
    };
    HTMLDialogElement.prototype.close = function () {
      this.open = false;
    };
    const onSeasonChange = vi.fn();
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    const button = (name: string) =>
      [...document.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
        item.textContent?.includes(name),
      )!;
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{ owner: true, permissions: [] }}
          >
            <RosterWorkspace
              seasonId="1"
              seasons={[]}
              onSeasonChange={onSeasonChange}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      const input = document.querySelector<HTMLInputElement>(
        'input[aria-label="Weight draft"]',
      )!;
      await act(async () => {
        input.focus();
        Object.getOwnPropertyDescriptor(
          HTMLInputElement.prototype,
          "value",
        )!.set!.call(input, "750");
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
      expect(input.value).toBe("750");
      await act(async () =>
        button(
          destination === "tab"
            ? "Compare clans"
            : destination === "season"
              ? "Next season"
              : "Set capacity",
        ).click(),
      );
      expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
        "You have 1 unsaved weight.",
      );
      expect(confirm).not.toHaveBeenCalled();
      expect(onSeasonChange).not.toHaveBeenCalled();
      await act(async () => button("Keep editing").click());
      expect(input.value).toBe("750");
      expect(document.activeElement).toBe(input);
      await act(async () =>
        button(
          destination === "tab"
            ? "Compare clans"
            : destination === "season"
              ? "Next season"
              : "Set capacity",
        ).click(),
      );
      await act(async () =>
        document
          .querySelector<HTMLDialogElement>(".confirm-dialog")!
          .dispatchEvent(
            new Event("cancel", { bubbles: true, cancelable: true }),
          ),
      );
      expect(input.value).toBe("750");
      await act(async () =>
        button(
          destination === "tab"
            ? "Compare clans"
            : destination === "season"
              ? "Next season"
              : "Set capacity",
        ).click(),
      );
      await act(async () =>
        document.querySelector<HTMLDialogElement>(".confirm-dialog")!.click(),
      );
      expect(input.value).toBe("750");
      await act(async () =>
        button(
          destination === "tab"
            ? "Compare clans"
            : destination === "season"
              ? "Next season"
              : "Set capacity",
        ).click(),
      );
      await act(async () => button("Discard").click());
      expect(confirm).not.toHaveBeenCalled();
      if (destination === "tab")
        expect(host.textContent).toContain("Comparison opened");
      if (destination === "season")
        expect(onSeasonChange).toHaveBeenCalledExactlyOnceWith("2");
      if (destination === "capacity")
        expect(button("Clan settings").getAttribute("aria-pressed")).toBe(
          "true",
        );
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);

it("defers a clan pool switch and runs the chosen pool after Discard", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  sessionStorage.setItem("wu-roster-1-mode", '"rules"');
  state.api.mockResolvedValue({
    revision: 1,
    accounts: [],
    clans: [],
    metadata_updating: false,
  });
  const confirm = vi.fn(() => false);
  window.confirm = confirm;
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const button = (name: string) =>
    [...document.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
      item.textContent?.includes(name),
    )!;
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
    await act(async () => button("Edit clan setting").click());
    await act(async () => button("Lazy CWL").click());
    expect(button("Main CWL").getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "You have unsaved roster changes.",
    );
    await act(async () => button("Keep editing").click());
    expect(button("Main CWL").getAttribute("aria-pressed")).toBe("true");
    await act(async () => button("Lazy CWL").click());
    await act(async () => button("Discard").click());
    expect(button("Lazy CWL").getAttribute("aria-pressed")).toBe("true");
    expect(confirm).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("does not discard a queued pool change if a save starts before confirmation", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  sessionStorage.setItem("wu-roster-1-mode", '"rules"');
  state.api.mockResolvedValue({
    revision: 1,
    accounts: [],
    clans: [],
    metadata_updating: false,
  });
  window.confirm = vi.fn(() => false);
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const button = (name: string) =>
    [...document.querySelectorAll<HTMLButtonElement>("button")].find((item) =>
      item.textContent?.includes(name),
    )!;
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
    await act(async () => button("Edit clan setting").click());
    await act(async () => button("Lazy CWL").click());
    await act(async () => button("Begin save").click());
    await act(async () => button("Discard").click());
    expect(button("Main CWL").getAttribute("aria-pressed")).toBe("true");
    expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
      "Wait for the save to finish.",
    );
    expect(
      document.querySelector(".confirm-dialog")?.textContent,
    ).not.toContain("Discard");
    await act(async () => button("OK").click());
    expect(document.querySelector(".confirm-dialog")).toBeNull();
    expect(window.confirm).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("keeps selection across assign pool filters without a discard dialog", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const account = {
    tag: "#P2Y",
    user_id: "1",
    player_name: "Selected player",
    pool: "main",
    town_hall: 16,
    effective_weight: 120000,
    assigned_clan_tag: null,
    kept: false,
    source_status: "current",
    source_weight: 120000,
    manual_weight: null,
  };
  state.api.mockResolvedValue({
    revision: 1,
    accounts: [account],
    clans: [],
    metadata_updating: false,
  });
  window.confirm = vi.fn(() => false);
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const poolButton = (name: string) =>
    [
      ...host.querySelectorAll<HTMLButtonElement>(
        ".roster-list-pool-tabs button",
      ),
    ].find((b) => b.textContent?.trim() === name)!;
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
    await act(async () =>
      host
        .querySelector<HTMLInputElement>(
          'input[aria-label="Select Selected player for bulk actions"]',
        )!
        .click(),
    );
    expect(
      document.querySelector(".roster-selection-dock")?.textContent,
    ).toContain("1 selected");
    for (const pool of ["Main CWL", "Lazy CWL", "All accounts"]) {
      await act(async () => poolButton(pool).click());
      expect(document.querySelector(".confirm-dialog")).toBeNull();
      expect(poolButton(pool).getAttribute("aria-pressed")).toBe("true");
      expect(
        document.querySelector(".roster-selection-dock")?.textContent,
      ).toContain("1 selected");
    }
    expect(window.confirm).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
