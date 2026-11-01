// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import RosterMenu from "./Menu";
it("searches clan name/tag without losing disabled choices or changing selection", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const change = vi.fn();
  try {
    await act(async () =>
      root.render(
        <RosterMenu
          searchable
          label="Hosting clan"
          value="#PYY"
          onValueChange={change}
          options={[
            { value: "#PYY", label: "Ｆａｍｉｌｙ North" },
            { value: "#PQQ", label: "South", disabled: true },
          ]}
        />,
      ),
    );
    await act(async () => host.querySelector("button")!.click());
    const input = document.querySelector<HTMLInputElement>(
      'dialog input[type="search"]',
    )!;
    expect(input).not.toBeNull();
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "family");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(
      document.querySelector('dialog [role="menu"]')!.textContent,
    ).toContain("Ｆａｍｉｌｙ North");
    expect(
      document.querySelector('dialog [role="menu"]')!.textContent,
    ).not.toContain("South");
    expect(change).not.toHaveBeenCalled();
    await act(async () => {
      Object.getOwnPropertyDescriptor(
        HTMLInputElement.prototype,
        "value",
      )!.set!.call(input, "#PQQ");
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    expect(
      document.querySelector('[role="menuitem"][aria-disabled="true"]'),
    ).not.toBeNull();
    expect(change).not.toHaveBeenCalled();
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
