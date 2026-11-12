// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
import BonusWorkspace from "./BonusWorkspace";
const account = {
  tag: "#PYY",
  player_name: "Fixture",
  pool: "lazy",
  assigned_clan_tag: "#PQQ",
  assigned_clan_name: "Family",
  town_hall: 16,
  attacks: 3,
  stars: 9,
  notes: "",
  revision: 1,
  in_latest_publication: true,
  source_status: "ready",
  source_complete: true,
  manual_candidate: true,
};
const data = {
  season_status: "draft",
  cycle: "2026-11",
  revision: 1,
  policies: { main: 3, lazy: null },
  policy: {},
  clans: [{ tag: "#PQQ", name: "Family", slots: null }],
  accounts: [account],
  draws: [],
  history: [],
  cycle_confirmed: [],
  active_other_cycles: [],
  sync: { enabled: false, warning: null, last_checked_at: null },
  publication_version: 1,
};
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  sessionStorage.clear();
  localStorage.setItem("wu-staff-cwl-pool", "lazy");
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  api.mockReset().mockResolvedValue(data);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <BonusWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
        ]}
        urlState="pool=lazy&clan=%23PQQ"
        onSeasonChange={() => {}}
      />,
    ),
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("removing a manual candidate requires confirm, Cancel writes zero and double tap writes once", async () => {
  const review = host.querySelector<HTMLButtonElement>(
    ".bonus-account-list .account-card-open",
  )!;
  await act(async () => review.click());
  await act(async () => button("Remove candidate").click());
  expect(writes()).toHaveLength(0);
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(writes()).toHaveLength(0);
  await act(async () => {
    button("Remove candidate").click();
    button("Remove candidate").click();
  });
  await act(async () => {
    const confirm = button(
      "Remove candidate",
      document.querySelector(".confirm-dialog")!,
    );
    confirm.click();
    confirm.click();
  });
  expect(writes()).toHaveLength(1);
  expect(writes()[0]).toEqual([
    "/seasons/1/bonus-raffle/manual-candidates",
    "DELETE",
    { tag: "#PYY", revision: 1 },
  ]);
});
it("candidate discard Cancel keeps the edit; confirmed discard closes without writing", async () => {
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        ".bonus-account-list .account-card-open",
      )!
      .click(),
  );
  const input = document.querySelector<HTMLTextAreaElement>(
    ".bonus-review-editor textarea",
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(input, "Local exception");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () =>
    button("Cancel", document.querySelector(".bonus-review-editor")!).click(),
  );
  expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(input.value).toBe("Local exception");
  expect(writes()).toHaveLength(0);
  await act(async () =>
    button("Cancel", document.querySelector(".bonus-review-editor")!).click(),
  );
  await act(async () =>
    button(
      "Discard candidate edits",
      document.querySelector(".confirm-dialog")!,
    ).click(),
  );
  expect(document.querySelector(".bonus-review-editor")).toBeNull();
  expect(writes()).toHaveLength(0);
});
it("the whole card opens Review in a modal panel, not below the list", async () => {
  const open = host.querySelector<HTMLButtonElement>(
    ".bonus-account-list .account-card-open",
  )!;
  expect(open.getAttribute("aria-label")).toBe("Review Fixture");
  await act(async () => open.click());
  const panel = document.querySelector<HTMLDialogElement>(
    "dialog.action-panel.bonus-review-editor",
  )!;
  expect(panel.open).toBe(true);
  // Portaled to the page body, so it never lands at the end of the list.
  expect(host.contains(panel)).toBe(false);
  expect(panel.textContent).toContain("Infractions for Fixture");
  await act(async () =>
    panel.querySelector<HTMLButtonElement>(".action-panel-close")!.click(),
  );
  expect(document.querySelector(".bonus-review-editor")).toBeNull();
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(writes()).toHaveLength(0);
});
it("Escape with unsaved review edits asks before closing and writes nothing", async () => {
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        ".bonus-account-list .account-card-open",
      )!
      .click(),
  );
  const panel = document.querySelector<HTMLDialogElement>(
    ".bonus-review-editor",
  )!;
  await act(async () =>
    panel.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(),
  );
  await act(async () => {
    panel.dispatchEvent(new Event("cancel", { cancelable: true }));
  });
  expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(document.querySelector(".bonus-review-editor")).not.toBeNull();
  expect(
    panel.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked,
  ).toBe(true);
  expect(writes()).toHaveLength(0);
});
