// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
// Exercise the parent's real guarded POST with its existing child dirty-state contract.
// This signal represents a retained result edit; it is not a live editor/Discord test.
vi.mock("./ParticipationRecord", () => ({
  default: ({
    account,
    onDirty,
  }: {
    account: { tag: string };
    onDirty: (tag: string, dirty: boolean) => void;
  }) => (
    <button onClick={() => onDirty(account.tag, true)}>
      Retain local result edit
    </button>
  ),
}));
import ParticipationWorkspace from "./ParticipationWorkspace";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const sync = {
  cycle: "2026-11",
  enabled: false,
  cycle_source: "settings",
  status: "waiting",
  warning: null,
  last_checked_at: null,
  last_success_at: null,
  updated_at: "2026-11-01T00:00:00Z",
};
const data = {
  accounts: [
    {
      tag: "#PYY",
      player_name: "Fixture",
      pool: "main",
      assigned_clan_tag: "#PQQ",
      assigned_clan_name: "Family",
      attacks: 1,
      stars: 3,
      town_hall: 18,
      notes: "",
      revision: 1,
      in_latest_publication: true,
    },
  ],
  publication_version: 1,
  sync,
};
const button = (text: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
const posts = () => api.mock.calls.filter((call) => call[1] === "POST");
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  sessionStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  api
    .mockReset()
    .mockImplementation(async (_path: string, method?: string) =>
      method === "POST" ? { sync: { ...sync, cycle: "2026-12" } } : data,
    );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ParticipationWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        onSeasonChange={() => {}}
      />,
    ),
  );
  await act(async () => button("Retain local result edit").click());
  host.querySelector<HTMLDetailsElement>(
    ".participation-capture-settings",
  )!.open = true;
  const month = host.querySelector<HTMLInputElement>('input[type="month"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(month, "2026-12");
    month.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(button("Save capture settings").disabled).toBe(false);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("Change CWL month Cancel sends zero sync-settings POSTs and preserves the month edit", async () => {
  await act(async () => button("Save capture settings").click());
  expect(posts()).toHaveLength(0);
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "unsaved result edits for 1 account",
  );
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(posts()).toHaveLength(0);
  expect(
    host.querySelector<HTMLInputElement>('input[type="month"]')!.value,
  ).toBe("2026-12");
});
it.each([false, true])(
  "Change CWL month confirms exactly one POST (double tap %s)",
  async (double) => {
    await act(async () => {
      button("Save capture settings").click();
      if (double) button("Save capture settings").click();
    });
    expect(posts()).toHaveLength(0);
    await act(async () => {
      const confirm = button(
        "Change CWL month",
        document.querySelector(".confirm-dialog")!,
      );
      confirm.click();
      if (double) confirm.click();
    });
    expect(posts()).toEqual([
      [
        "/seasons/1/participation/sync-settings",
        "POST",
        {
          cycle: "2026-12",
          enabled: false,
          expected_updated_at: "2026-11-01T00:00:00Z",
        },
      ],
    ]);
  },
);
