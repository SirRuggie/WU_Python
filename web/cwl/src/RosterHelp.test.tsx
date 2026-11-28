// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterHelp from "./RosterHelp";

it("keeps Auto-place help closed until selected, then returns focus to the ?", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const back = vi.spyOn(history, "back").mockImplementation(() => {});
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<RosterHelp />));
    expect(document.body.textContent).not.toContain(
      "Auto-place puts unassigned accounts",
    );
    const trigger = host.querySelector<HTMLButtonElement>(
      '[aria-label="How Auto-place works"]',
    )!;
    await act(async () => trigger.click());
    const dialog = document.querySelector<HTMLDialogElement>("dialog")!;
    expect(dialog.open).toBe(true);
    expect(
      [...dialog.querySelectorAll("h3")].map((h) => h.textContent),
    ).toEqual(["Auto-place", "One member, many accounts", "Order", "Balance"]);
    await act(async () => {
      dialog.dispatchEvent(
        new Event("cancel", { bubbles: false, cancelable: true }),
      );
    });
    expect(document.querySelector("dialog")).toBeNull();
    expect(document.activeElement).toBe(trigger);
  } finally {
    await act(async () => root.unmount());
    host.remove();
    back.mockRestore();
    history.replaceState({}, "");
  }
});

it("puts Auto-place help in the Build roster page header", () => {
  const header = readFileSync("src/RosterHeader.tsx", "utf8");
  expect(header).toContain("help={<RosterHelp />}");
});
