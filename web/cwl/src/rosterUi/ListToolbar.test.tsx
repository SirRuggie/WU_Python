// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ActionPanel from "../ActionPanel";
import SectionTabs from "../SectionTabs";
import FiltersTrigger from "./FiltersTrigger";
import ListToolbar from "./ListToolbar";
import SortTrigger from "./SortTrigger";

let host: HTMLDivElement, root: Root;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  history.replaceState({}, "", "/fixture");
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  vi.spyOn(HTMLElement.prototype, "getClientRects").mockImplementation(
    function (this: HTMLElement) {
      return this.isConnected
        ? ([new DOMRect(0, 0, 44, 44)] as unknown as DOMRectList)
        : ([] as unknown as DOMRectList);
    },
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it("keeps scope, Filters, Sort and actions in reading order, with optional slots", async () => {
  await act(async () =>
    root.render(
      <ListToolbar
        scope={
          <SectionTabs
            mode="segmented"
            label="Scope"
            value="all"
            items={[
              { id: "all", label: "All" },
              { id: "main", label: "Main" },
            ]}
            onChange={() => {}}
          />
        }
        filters={<FiltersTrigger count={2} open={false} />}
        sort={<SortTrigger label="Name" />}
        actions={<button>Existing action</button>}
      />,
    ),
  );
  const controls = [...host.querySelectorAll("button")];
  expect(controls.map((button) => button.textContent)).toEqual([
    "All",
    "Main",
    "Filters · 2",
    "Name",
    "Existing action",
  ]);
  expect(host.querySelector('[aria-label="Scope"]')?.getAttribute("role")).toBe(
    "group",
  );
  expect(controls[0].getAttribute("aria-pressed")).toBe("true");
  expect(controls[2].getAttribute("aria-expanded")).toBe("false");
  await act(async () =>
    root.render(
      <ListToolbar filters={<FiltersTrigger count={0} open={false} />} />,
    ),
  );
  expect(host.querySelectorAll("button")).toHaveLength(1);
  expect(host.textContent).toBe("Filters");
});

it("opens the existing ActionPanel, traps Tab and returns focus after native Escape cancel", async () => {
  function Harness() {
    const [open, setOpen] = useState(false);
    const [trigger, setTrigger] = useState<HTMLElement | null>(null);
    return (
      <>
        <ListToolbar
          filters={
            <FiltersTrigger
              count={1}
              open={open}
              onClick={(event) => {
                setTrigger(event.currentTarget);
                setOpen(true);
              }}
            />
          }
        />
        {open && (
          <ActionPanel
            title="Filter fixture"
            trigger={trigger}
            onClose={() => setOpen(false)}
          >
            <button>Filter option</button>
          </ActionPanel>
        )}
      </>
    );
  }
  await act(async () => root.render(<Harness />));
  const trigger = host.querySelector<HTMLButtonElement>("button")!;
  await act(async () => trigger.click());
  const dialog = document.querySelector<HTMLDialogElement>("dialog")!;
  expect(dialog.open).toBe(true);
  expect(trigger.getAttribute("aria-expanded")).toBe("true");
  const option = [...dialog.querySelectorAll<HTMLButtonElement>("button")].find(
    (button) => button.textContent === "Filter option",
  )!;
  option.focus();
  await act(async () =>
    option.dispatchEvent(
      new KeyboardEvent("keydown", {
        key: "Tab",
        bubbles: true,
        cancelable: true,
      }),
    ),
  );
  expect(document.activeElement).toBe(
    dialog.querySelector('[aria-label="Close panel"]'),
  );
  await act(async () =>
    dialog.dispatchEvent(
      new Event("cancel", { bubbles: false, cancelable: true }),
    ),
  );
  await act(
    async () =>
      new Promise<void>((resolve) => requestAnimationFrame(() => resolve())),
  );
  expect(document.querySelector("dialog")).toBeNull();
  expect(trigger.getAttribute("aria-expanded")).toBe("false");
  expect(document.activeElement).toBe(trigger);
});

it("allows a scope and actions without a Filters slot", async () => {
  await act(async () =>
    root.render(
      <ListToolbar
        scope={<button>Main</button>}
        actions={<button>Add signup</button>}
      />,
    ),
  );
  expect(
    [...host.querySelectorAll("button")].map((item) => item.textContent),
  ).toEqual(["Main", "Add signup"]);
});
