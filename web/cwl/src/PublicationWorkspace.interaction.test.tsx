// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import PublicationWorkspace from "./PublicationWorkspace";
import { publicationBlockingReason } from "./publicationBlockingReason";
import { DashboardPermissions } from "./DashboardPermissions";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({
  api,
  ApiError: class extends Error {
    status = 409;
  },
}));
vi.mock("./ClanRosterImages", () => ({ default: () => null }));
vi.mock("./ManageBridgeWorkspace", () => ({ default: () => null }));
vi.mock("./StaffPlayerButton", () => ({ default: () => null }));
it("Announcements skips comparison; readiness gates publishing; Cancel and stale revision send no write", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  const account = {
    tag: "#P",
    player_name: "Ann",
    user_id: "1",
    pool: "main",
    town_hall: 18,
    assigned_clan_tag: "#A",
    effective_weight: 170000,
    kept: false,
  };
  let draft = {
    last_publication: null,
    next_version: 2,
    draft_revision: 7,
    draft_changed: true,
    published: { version: 1, published_at: "2026-10-27T00:00:00Z" },
    preview: {
      accounts: [account],
      clans: [
        { tag: "#A", name: "Clan A", pool: "main", effective_capacity: 15 },
      ],
      assigned_count: 1,
      unassigned_count: 0,
    },
  };
  let finishComparison!: (value: unknown) => void;
  api.mockImplementation(async (path: string) =>
    path.includes("export-preview")
      ? new Promise((resolve) => {
          finishComparison = resolve;
        })
      : draft,
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const render = (step: "review" | "announce") =>
    root.render(
      <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
        <PublicationWorkspace
          seasonId="1"
          seasons={
            [{ id: 1, label: "November 2026", status: "draft" }] as never
          }
          onSeasonChange={() => {}}
          onFix={() => {}}
          step={step}
          onStepChange={() => {}}
        />
      </DashboardPermissions.Provider>,
    );
  await act(async () => render("announce"));
  expect(api.mock.calls.some(([path]) => path.includes("export-preview"))).toBe(
    false,
  );
  await act(async () => render("review"));
  const button = [...host.querySelectorAll("button")].find(
    (e) => e.textContent === "Publish updated roster",
  )!;
  expect(button.disabled).toBe(true);
  expect(host.querySelector("#publish-blocked-reason")).toBeNull();
  expect(host.textContent).toContain("Loading changes…");
  expect(host.querySelectorAll(".cwl-next-cue")).toHaveLength(1);
  await act(async () =>
    finishComparison({
      rows: [{ ...account, assigned_clan_tag: "#B" }],
      summary: { published_version: 1 },
    }),
  );
  expect(button.disabled).toBe(false);
  expect(host.querySelector("#publish-blocked-reason")).toBeNull();
  const text = host.textContent!;
  expect(text.indexOf("Members still see")).toBeLessThan(
    text.indexOf("Publishing creates version"),
  );
  expect(text.indexOf("Publishing creates version")).toBeLessThan(
    text.indexOf("Before you publish"),
  );
  expect(text.indexOf("Before you publish")).toBeLessThan(
    text.indexOf("Joining instructions"),
  );
  expect(text.indexOf("Joining instructions")).toBeLessThan(
    text.indexOf("Full roster preview"),
  );
  expect(
    host.querySelector<HTMLDetailsElement>(".publication-preview")!.open,
  ).toBe(false);
  expect(
    [...host.querySelectorAll("button")].filter(
      (e) => e.textContent === "Refresh draft",
    ),
  ).toHaveLength(1);
  expect(document.querySelector("dialog")).toBeNull();
  await act(async () => button.click());
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Publish version 2?",
  );
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
  await act(async () =>
    [...document.querySelectorAll("dialog button")]
      .find((e) => e.textContent === "Cancel")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true })),
  );
  expect(document.querySelector("dialog")).toBeNull();
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
  // A read completes with a new revision while the confirmation is open.
  await act(async () => button.click());
  draft = { ...draft, draft_revision: 8 };
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((e) => e.textContent === "Refresh draft")!
      .click(),
  );
  await act(async () =>
    finishComparison({ rows: [account], summary: { published_version: 1 } }),
  );
  await act(async () =>
    [...document.querySelectorAll("dialog button")]
      .find((e) => e.textContent === "Publish roster")!
      .dispatchEvent(new MouseEvent("click", { bubbles: true })),
  );
  expect(host.textContent).toContain(
    "The draft changed. Review it again before publishing.",
  );
  expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
    true,
  );
  expect(host.querySelectorAll(".cwl-next-cue")).toHaveLength(1);
  expect(host.querySelector(".cwl-next-cue")?.textContent).toBe(
    "Next: Announcements ›",
  );
  act(() => root.unmount());
  host.remove();
  api.mockReset();
});
it("publication review exposes the explicit filler count without an over-capacity warning", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockResolvedValue({
    last_publication: null,
    next_version: 1,
    draft_revision: 1,
    draft_changed: true,
    published: null,
    preview: {
      accounts: Array.from({ length: 16 }, (_, i) => ({
        tag: String(i),
        player_name: "Member",
        pool: "main",
        assigned_clan_tag: "#A",
        roster_filler: i === 0,
        effective_weight: 100000,
        town_hall: 16,
      })),
      clans: [{ tag: "#A", name: "A", pool: "main", effective_capacity: 15 }],
      assigned_count: 16,
      unassigned_count: 0,
    },
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider value={{ owner: true, permissions: [] }}>
          <PublicationWorkspace
            seasonId="1"
            seasons={[] as never}
            onSeasonChange={() => {}}
            onFix={() => {}}
            step="review"
            onStepChange={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    expect(host.textContent).toContain("+1 filler");
    expect(host.querySelector(".publication-over")).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("publish-only users do not receive the Announcements Next destination", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const draft = {
    next_version: 2,
    draft_revision: 1,
    draft_changed: false,
    published: { version: 1, published_at: "2026-11-01T00:00:00Z" },
    preview: {
      accounts: [],
      clans: [],
      assigned_count: 0,
      unassigned_count: 0,
    },
  };
  api.mockImplementation(async (path: string) =>
    path.includes("export-preview")
      ? { rows: [], summary: { published_version: 1 } }
      : draft,
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider
          value={{ owner: false, permissions: ["cwl_publish"] }}
        >
          <PublicationWorkspace
            seasonId="1"
            seasons={[]}
            onSeasonChange={() => {}}
            onFix={() => {}}
            step="review"
            onStepChange={() => {}}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    expect(host.querySelector(".cwl-next-cue")).toBeNull();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("unsaved instructions disable the persisted Next cue until restored", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const draft = {
    next_version: 2,
    draft_revision: 1,
    draft_changed: false,
    published: {
      version: 1,
      joining_instructions: "Saved instructions",
      published_at: "2026-11-01T00:00:00Z",
    },
    preview: {
      accounts: [],
      clans: [],
      assigned_count: 0,
      unassigned_count: 0,
    },
  };
  api.mockImplementation(async (path: string) =>
    path.includes("export-preview")
      ? { rows: [], summary: { published_version: 1 } }
      : draft,
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onDirty = vi.fn();
  try {
    await act(async () =>
      root.render(
        <DashboardPermissions.Provider
          value={{ owner: false, permissions: ["cwl_publish", "cwl_send"] }}
        >
          <PublicationWorkspace
            seasonId="1"
            seasons={[]}
            onSeasonChange={() => {}}
            onFix={() => {}}
            step="review"
            onStepChange={() => {}}
            onDirty={onDirty}
          />
        </DashboardPermissions.Provider>,
      ),
    );
    const next = host.querySelector<HTMLButtonElement>(".cwl-next-cue")!;
    expect(next.disabled).toBe(false);
    const input = host.querySelector<HTMLTextAreaElement>("textarea")!;
    const change = async (value: string) =>
      act(async () => {
        Object.getOwnPropertyDescriptor(
          HTMLTextAreaElement.prototype,
          "value",
        )!.set!.call(input, value);
        input.dispatchEvent(new Event("input", { bubbles: true }));
      });
    await change("Changed instructions");
    expect(onDirty).toHaveBeenLastCalledWith(true);
    expect(next.disabled).toBe(true);
    await change("Saved instructions");
    expect(onDirty).toHaveBeenLastCalledWith(false);
    expect(next.disabled).toBe(false);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it.each([
  { name: "ready" },
  { name: "permission", noPermission: true },
  { name: "archived", archived: true },
  { name: "no accounts", empty: true },
  { name: "unplaced", unplaced: true },
  { name: "instructions too long", tooLong: true },
  { name: "comparison failed", comparisonError: true },
])(
  "actual canPublish and blocking explanation agree: $name",
  async (testCase) => {
    Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
    const config = {
      noPermission: false,
      archived: false,
      empty: false,
      unplaced: false,
      tooLong: false,
      comparisonError: false,
      ...testCase,
    };
    const account = {
      tag: "#P",
      player_name: "Player",
      user_id: "1",
      pool: "main",
      town_hall: 18,
      assigned_clan_tag: config.unplaced ? null : "#A",
      effective_weight: 170000,
    };
    const draft = {
      next_version: 2,
      draft_revision: 1,
      draft_changed: true,
      published: {
        version: 1,
        joining_instructions: config.tooLong ? "x".repeat(2001) : "Saved",
        published_at: "2026-11-01T00:00:00Z",
      },
      preview: {
        accounts: config.empty ? [] : [account],
        clans: [
          { tag: "#A", name: "Clan A", pool: "main", effective_capacity: 15 },
        ],
        assigned_count: config.unplaced || config.empty ? 0 : 1,
        unassigned_count: config.unplaced ? 1 : 0,
      },
    };
    api.mockImplementation(async (path: string) => {
      if (path.includes("export-preview")) {
        if (config.comparisonError)
          throw new Error("Fixture comparison failed");
        return { rows: [], summary: { published_version: 1 } };
      }
      return draft;
    });
    const host = document.createElement("div");
    document.body.append(host);
    const root = createRoot(host);
    try {
      await act(async () =>
        root.render(
          <DashboardPermissions.Provider
            value={{
              owner: false,
              permissions: config.noPermission ? ["cwl_send"] : ["cwl_publish"],
            }}
          >
            <PublicationWorkspace
              seasonId="1"
              seasons={
                [
                  {
                    id: 1,
                    label: "November",
                    status: config.archived ? "archived" : "draft",
                  },
                ] as never
              }
              onSeasonChange={() => {}}
              onFix={() => {}}
              step="review"
              onStepChange={() => {}}
            />
          </DashboardPermissions.Provider>,
        ),
      );
      const button = [
        ...host.querySelectorAll<HTMLButtonElement>("button"),
      ].find((node) => node.textContent?.trim() === "Publish updated roster")!;
      const reason = publicationBlockingReason({
        hasDraft: true,
        canManage: !config.noPermission,
        locked: false,
        loading: false,
        hasError: false,
        archived: config.archived,
        instructionsLength: config.tooLong ? 2001 : 5,
        changesReady: !config.comparisonError,
        comparisonStatus: config.comparisonError ? "error" : "ready",
        accounts: config.empty ? 0 : 1,
        unplaced: config.unplaced ? 1 : 0,
        acknowledged: false,
      });
      expect(button.disabled).toBe(!!reason);
      expect(
        host.querySelector("#publish-blocked-reason")?.textContent || "",
      ).toBe(reason);
    } finally {
      await act(async () => root.unmount());
      host.remove();
    }
  },
);
