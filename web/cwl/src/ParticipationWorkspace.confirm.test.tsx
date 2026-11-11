// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import ParticipationWorkspace from "./ParticipationWorkspace";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const change = vi.fn(),
  data = {
    accounts: [],
    publication_version: 1,
    sync: {
      cycle: "2026-11",
      enabled: false,
      cycle_source: "settings",
      status: "waiting",
      warning: null,
      last_checked_at: null,
      last_success_at: null,
      updated_at: null,
    },
  };
const button = (name: string, within: ParentNode = document) =>
  [...within.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.trim() === name,
  )!;
const writes = () =>
  api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
// Refresh list sits in the capture card's shared ⋯ menu (prompt 228).
async function menuAction(label: string) {
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        ".participation-capture .roster-action-trigger",
      )!
      .click(),
  );
  const item = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((e) => e.textContent?.trim() === label)!;
  await act(async () => {
    item.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, button: 0 }),
    );
    item.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0 }));
    item.click();
  });
}
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  api.mockReset().mockResolvedValue(data);
  change.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <ParticipationWorkspace
        seasonId="1"
        seasons={[
          { id: 1, label: "November", status: "draft", signup_open: true },
          { id: 2, label: "December", status: "draft", signup_open: true },
        ]}
        onSeasonChange={change}
      />,
    ),
  );
  host.querySelector("details")!.open = true;
  const month = host.querySelector<HTMLInputElement>('input[type="month"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(month, "2026-12");
    month.dispatchEvent(new Event("input", { bubbles: true }));
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("Refresh Cancel retains unsaved month, confirmed refresh reads once and never saves", async () => {
  const before = api.mock.calls.length;
  await menuAction("Refresh list");
  expect(api.mock.calls).toHaveLength(before);
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(
    host.querySelector<HTMLInputElement>('input[type="month"]')!.value,
  ).toBe("2026-12");
  expect(writes()).toHaveLength(0);
  await menuAction("Refresh list");
  await menuAction("Refresh list");
  await act(async () => {
    const confirm = button(
      "Discard and refresh",
      document.querySelector(".confirm-dialog")!,
    );
    confirm.click();
    confirm.click();
  });
  expect(api.mock.calls).toHaveLength(before + 1);
  expect(writes()).toHaveLength(0);
  expect(
    host.querySelector<HTMLInputElement>('input[type="month"]')!.value,
  ).toBe("2026-11");
});
it("season change cancellation and double confirmation preserve callback value and zero writes", async () => {
  // The season field is the short-list native select (prompt 228).
  async function select() {
    const field = host.querySelector<HTMLSelectElement>(
      '.cwl-page-header select[name="season"]',
    )!;
    await act(async () => {
      field.value = "2";
      field.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }
  await select();
  expect(change).not.toHaveBeenCalled();
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(change).not.toHaveBeenCalled();
  await select();
  await act(async () => {
    const confirm = button(
      "Discard and change season",
      document.querySelector(".confirm-dialog")!,
    );
    confirm.click();
    confirm.click();
  });
  expect(change).toHaveBeenCalledExactlyOnceWith("2");
  expect(writes()).toHaveLength(0);
});
