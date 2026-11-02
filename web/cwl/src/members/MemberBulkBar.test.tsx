// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import MemberBulkBar from "./MemberBulkBar";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function render(busy = false, selected = false) {
  const clear = vi.fn(),
    add = vi.fn();
  await act(async () =>
    root.render(
      <MemberBulkBar
        pageSelected={selected}
        pagePartial={true}
        onSelectPage={() => {}}
        matchingCount={25}
        onSelectMatching={() => {}}
        count={1411}
        hidden={1410}
        canRoles={true}
        canProfiles={true}
        busy={busy}
        onShow={() => {}}
        onAdd={add}
        onRemove={() => {}}
        onFix={() => {}}
        onClear={clear}
      />,
    ),
  );
  const trigger = host.querySelector<HTMLButtonElement>(
    'button[aria-label="Actions"]',
  )!;
  expect(trigger.disabled).toBe(false);
  await act(async () => trigger.click());
  return { clear, add };
}
it("phone Actions keeps Clear available while writes are disabled", async () => {
  const { clear, add } = await render(true);
  const items = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ];
  expect(items.map((e) => e.textContent)).toEqual([
    "Add role",
    "Remove role",
    "Fix nicknames",
    "Select page",
    "Select all 25 matching",
    "Select none",
  ]);
  expect(items[0].getAttribute("aria-disabled")).toBe("true");
  expect(items[5].getAttribute("aria-disabled")).not.toBe("true");
  await act(async () => items[5].click());
  expect(clear).toHaveBeenCalledTimes(1);
  expect(add).not.toHaveBeenCalled();
});
it("phone Actions exposes Add role without scrolling past selection tools", async () => {
  const { add } = await render();
  const item = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((e) => e.textContent === "Add role")!;
  await act(async () => item.click());
  expect(add).toHaveBeenCalledTimes(1);
});

it("selected page exposes Unselect page and preserves the hidden count", async () => {
  await render(false, true);
  expect(document.querySelector('[role="menu"]')?.textContent).toContain(
    "Unselect page",
  );
  expect(host.querySelector(".members-selection-short")?.textContent).toBe(
    "1411 · 1410 hidden",
  );
  expect(host.querySelector("button")?.getAttribute("aria-label")).toBe(
    "1411 selected · 1410 hidden",
  );
});
