// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import SectionTabs from "./SectionTabs";
import FilterChips from "./FilterChips";
import ClanSettingsNavigation from "./clanManagement/ClanSettingsNavigation";

let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(() => {
  act(() => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it("retains rich section labels, caller refs, own edge-fade state and per-option disabled guards", () => {
  const changed = vi.fn(),
    ref = vi.fn();
  act(() =>
    root.render(
      <SectionTabs
        label="Activity types"
        value="war"
        onChange={changed}
        rootRef={ref}
        data-fade-right="true"
        items={[
          {
            id: "war",
            label: (
              <>
                <span aria-hidden="true">icon</span>
                <strong>Wars</strong>
                <small>3 accounts</small>
              </>
            ),
          },
          { id: "raid", label: "Raids", disabled: true },
        ]}
      />,
    ),
  );
  const group = host.querySelector('[role="group"]')!;
  expect(ref).toHaveBeenCalledWith(group);
  // Fade state is measured by SectionTabs itself; a caller value cannot override it.
  expect(group.getAttribute("data-fade-right")).toBe("false");
  expect(group.classList.contains("has-horizontal-fades")).toBe(true);
  expect(group.querySelector("strong")?.textContent).toBe("Wars");
  expect(group.querySelector("small")?.textContent).toBe("3 accounts");
  const buttons = [...group.querySelectorAll("button")];
  buttons[0].focus();
  expect(document.activeElement).toBe(buttons[0]);
  for (const key of ["Enter", " "]) {
    const event = new KeyboardEvent("keydown", {
      key,
      bubbles: true,
      cancelable: true,
    });
    expect(buttons[0].dispatchEvent(event)).toBe(true);
    expect(event.defaultPrevented).toBe(false);
  }
  act(() => buttons[1].click());
  expect(changed).not.toHaveBeenCalled();
});

it("preserves numeric filter values and accessible names without inventing a count", () => {
  const changed = vi.fn();
  act(() =>
    root.render(
      <FilterChips<number>
        label="Town Hall level"
        role="group"
        variant="pill"
        value={null}
        options={[
          { value: 18, label: 18, ariaLabel: "Town Hall 18" },
          { value: 17, label: 17, ariaLabel: "Town Hall 17" },
        ]}
        onChange={changed}
      />,
    ),
  );
  expect(host.querySelector('[role="group"]')?.getAttribute("aria-label")).toBe(
    "Town Hall level",
  );
  expect(host.querySelector("small")).toBeNull();
  const buttons = [...host.querySelectorAll("button")];
  expect(buttons.map((b) => b.getAttribute("aria-pressed"))).toEqual([
    "false",
    "false",
  ]);
  expect(buttons.map((b) => b.getAttribute("aria-label"))).toEqual([
    "Town Hall 18",
    "Town Hall 17",
  ]);
  act(() => buttons[1].click());
  expect(changed.mock.calls).toEqual([[17]]);
});

it("keeps the real Clan settings tablist manual-activation keyboard and ID relationships", () => {
  const changed = vi.fn(),
    sections = ["Details", "Roles", "Channels"];
  act(() =>
    root.render(
      <ClanSettingsNavigation
        sections={sections}
        value="Details"
        disabled={false}
        onChange={changed}
      />,
    ),
  );
  expect(host.querySelector('[role="group"]')).toBeNull();
  const tabs = [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')];
  expect(tabs.map((t) => t.getAttribute("aria-controls"))).toEqual([
    "clan-panel-0",
    "clan-panel-1",
    "clan-panel-2",
  ]);
  expect(tabs.map((t) => t.id)).toEqual([
    "clan-section-0",
    "clan-section-1",
    "clan-section-2",
  ]);
  tabs[0].focus();
  for (const [index, key, target] of [
    [0, "ArrowRight", 1],
    [1, "End", 2],
    [2, "Home", 0],
    [0, "ArrowLeft", 2],
  ] as const) {
    act(() =>
      tabs[index].dispatchEvent(
        new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }),
      ),
    );
    expect(document.activeElement).toBe(tabs[target]);
  }
  expect(changed).not.toHaveBeenCalled();
  expect(tabs[0].getAttribute("aria-selected")).toBe("true");
  act(() => tabs[2].click());
  expect(changed.mock.calls).toEqual([["Channels"]]);
  act(() =>
    root.render(
      <ClanSettingsNavigation
        sections={sections}
        value="Channels"
        disabled
        onChange={changed}
      />,
    ),
  );
  act(() => tabs[0].click());
  expect(changed.mock.calls).toEqual([["Channels"]]);
});

it("reveals a restored selection in its strip without moving the document", () => {
  const pageScroll = vi.spyOn(window, "scrollTo");
  const originalRect = HTMLElement.prototype.getBoundingClientRect;
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    function (this: HTMLElement) {
      if (this.classList.contains("section-tabs"))
        return { left: 10, right: 210, width: 200 } as DOMRect;
      if (
        this.tagName === "BUTTON" &&
        this.parentElement?.classList.contains("section-tabs")
      ) {
        const index = [...this.parentElement.children].indexOf(this);
        const left = 10 + index * 120 - this.parentElement.scrollLeft;
        return { left, right: left + 110, width: 110 } as DOMRect;
      }
      return originalRect.call(this);
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("section-tabs") ? 200 : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("section-tabs") ? 590 : 0;
    },
  );
  const items = ["a", "b", "c", "d", "e"].map((id) => ({ id, label: id }));
  const render = (value: string) =>
    act(() =>
      root.render(
        <SectionTabs
          label="Sections"
          items={items}
          value={value}
          onChange={() => {}}
          revealSelection
        />,
      ),
    );
  render("e");
  const row = host.querySelector<HTMLElement>('[role="group"]')!;
  const selected = () =>
    row
      .querySelector<HTMLElement>('[aria-pressed="true"]')!
      .getBoundingClientRect();
  expect(selected().left).toBeGreaterThanOrEqual(10);
  expect(selected().right).toBeLessThanOrEqual(210);
  render("a");
  expect(selected().left).toBeGreaterThanOrEqual(10);
  expect(selected().right).toBeLessThanOrEqual(210);
  expect(pageScroll).not.toHaveBeenCalled();
});
