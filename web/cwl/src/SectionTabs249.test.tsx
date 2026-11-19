// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import SectionTabs, { SectionTabPanel } from "./SectionTabs";

it("uses manual activation, roving focus, disabled skipping, wrap, Home/End and linked panels", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const change = vi.fn();
  function Example() {
    const [value, setValue] = useState("a");
    return (
      <>
        <SectionTabs
          id="example"
          label="Views"
          value={value}
          onChange={(next) => {
            change(next);
            setValue(next);
          }}
          items={[
            { id: "a", label: "Alpha" },
            { id: "b", label: "Blocked", disabled: true },
            { id: "c", label: "Charlie" },
          ]}
        />
        <SectionTabPanel id="example" value={value}>
          {value}
        </SectionTabPanel>
      </>
    );
  }
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<Example />));
    const tabs = [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
    const key = async (at: number, key: string) =>
      act(async () => {
        tabs[at].dispatchEvent(
          new KeyboardEvent("keydown", {
            key,
            bubbles: true,
            cancelable: true,
          }),
        );
      });
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
    await key(0, "ArrowRight");
    expect(document.activeElement).toBe(tabs[2]);
    expect(change).not.toHaveBeenCalled();
    expect(tabs[0].getAttribute("aria-selected")).toBe("true");
    await key(2, "ArrowRight");
    expect(document.activeElement).toBe(tabs[0]);
    await key(0, "End");
    expect(document.activeElement).toBe(tabs[2]);
    await key(2, "Home");
    expect(document.activeElement).toBe(tabs[0]);
    await key(0, "ArrowLeft");
    expect(document.activeElement).toBe(tabs[2]);
    const outside = document.createElement("button");
    document.body.append(outside);
    await act(async () => outside.focus());
    expect(tabs.map((tab) => tab.tabIndex)).toEqual([0, -1, -1]);
    outside.remove();
    await act(async () => tabs[2].click());
    expect(change).toHaveBeenCalledExactlyOnceWith("c");
    const panel = host.querySelector('[role="tabpanel"]')!;
    expect(panel.id).toBe(tabs[2].getAttribute("aria-controls"));
    expect(panel.getAttribute("aria-labelledby")).toBe(tabs[2].id);
    expect(tabs[2].getAttribute("aria-selected")).toBe("true");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("retains pressed-button semantics for list-only filters", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div"),
    root = createRoot(host);
  try {
    await act(async () =>
      root.render(
        <SectionTabs
          mode="segmented"
          label="Pool filter"
          value="main"
          onChange={vi.fn()}
          items={[
            { id: "main", label: "Main" },
            { id: "lazy", label: "Lazy" },
          ]}
        />,
      ),
    );
    expect(host.querySelector('[role="group"]')).toBeTruthy();
    expect(host.querySelector('[role="tab"]')).toBeNull();
    expect(host.querySelector("button")?.getAttribute("aria-pressed")).toBe(
      "true",
    );
    expect(host.querySelector("button")?.hasAttribute("aria-controls")).toBe(
      false,
    );
  } finally {
    await act(async () => root.unmount());
  }
});
