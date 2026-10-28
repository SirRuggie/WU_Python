// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import PublicationWorkspace from "./PublicationWorkspace";
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
  await act(async () =>
    finishComparison({
      rows: [{ ...account, assigned_clan_tag: "#B" }],
      summary: { published_version: 1 },
    }),
  );
  expect(button.disabled).toBe(false);
  const text = host.textContent!;
  expect(text.indexOf("Members still see")).toBeLessThan(
    text.indexOf("Publishing creates version"),
  );
  expect(text.indexOf("Publishing creates version")).toBeLessThan(
    text.indexOf("Before you publish"),
  );
  expect(text.indexOf("Before you publish")).toBeLessThan(
    text.indexOf("Publish this roster"),
  );
  expect(text.indexOf("Publish this roster")).toBeLessThan(
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
  act(() => root.unmount());
  host.remove();
  api.mockReset();
});
