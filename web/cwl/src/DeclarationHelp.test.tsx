// @vitest-environment happy-dom
import { readFileSync } from "node:fs";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import DeclarationHelp from "./DeclarationHelp";

it("keeps readiness help closed until selected, then returns focus to the ?", async () => {
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
    await act(async () => root.render(<DeclarationHelp />));
    expect(document.body.textContent).not.toContain("The clan is full");
    const trigger = host.querySelector<HTMLButtonElement>(
      '[aria-label="About readiness"]',
    )!;
    await act(async () => trigger.click());
    const dialog = document.querySelector<HTMLDialogElement>("dialog")!;
    expect(dialog.open).toBe(true);
    expect(dialog.textContent).toContain(
      "The clan is full, checked in the last 5 minutes.",
    );
    expect(dialog.textContent).toContain("only for Lazy hosting clans");
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

it("puts readiness help in the Declaration check page header", () => {
  const app = readFileSync("src/App.tsx", "utf8");
  expect(app).toMatch(
    /title=\{<h1>Declaration check<\/h1>\} help=\{<DeclarationHelp \/>\}/,
  );
});
