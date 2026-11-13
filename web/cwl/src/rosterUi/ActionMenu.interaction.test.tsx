// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ActionMenu from "./ActionMenu";
import ActionPanel from "../ActionPanel";
import { closeRosterActionMenus } from "./actionMenuState";
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  act(() =>
    root.render(
      <>
        <div id="outside">Non-focusable outside</div>
        <ActionMenu
          name="One"
          items={[
            { id: "details", label: "Details", onAction: action },
            {
              id: "dm",
              label: "DM ↗",
              href: "https://discord.com/users/123456789012345678",
            },
          ]}
        />
        <ActionMenu
          name="Two"
          items={[{ id: "details", label: "Details", onAction: action }]}
        />
      </>,
    ),
  );
});
const action = vi.fn();
afterEach(() => {
  act(() => {
    root.unmount();
    closeRosterActionMenus();
  });
  host.remove();
  vi.clearAllMocks();
});
async function click(el: Element) {
  await act(async () => {
    el.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    el.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 }));
    el.dispatchEvent(
      new PointerEvent("pointerup", {
        bubbles: true,
        pointerType: "mouse",
        pointerId: 1,
        button: 0,
      }),
    );
    el.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0 }));
    (el as HTMLElement).click();
  });
}
const trigger = (name: string) =>
  document.querySelector(`[aria-label="Actions for ${name}"]`)!;
it("outside click closes even on a non-focusable container", async () => {
  await click(trigger("One"));
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
  await click(document.getElementById("outside")!);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});
it("opening a second menu leaves only the second open", async () => {
  await click(trigger("One"));
  await click(trigger("Two"));
  expect(document.querySelectorAll('[role="menu"]').length).toBe(1);
  expect(
    document.querySelector('[role="menu"]')?.getAttribute("aria-label"),
  ).toBe("Actions for Two");
});
it("Escape closes and returns focus to the trigger", async () => {
  const button = trigger("One");
  await click(button);
  await act(async () => {
    document
      .querySelector('[role="menu"]')!
      .dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true }),
      );
    await new Promise((r) => setTimeout(r, 30));
  });
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.activeElement).toBe(button);
});
it("choosing an item closes and runs its action once", async () => {
  await click(trigger("One"));
  await click(document.querySelector('[role="menuitem"]')!);
  expect(action).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});
it("preserves secure Discord link attributes", async () => {
  await click(trigger("One"));
  const link = document.querySelector('a[role="menuitem"]')!;
  expect(link.getAttribute("href")).toBe(
    "https://discord.com/users/123456789012345678",
  );
  expect(link.getAttribute("target")).toBe("_blank");
  expect(link.getAttribute("rel")).toBe("noopener noreferrer");
});

it("tapping the sheet heading keeps it open, but outside the sheet closes", async () => {
  await click(trigger("One"));
  await click(document.querySelector(".roster-action-heading")!);
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
  await click(document.getElementById("outside")!);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});

it("separates destructive actions semantically without activating them on open", async () => {
  await act(async () =>
    root.render(
      <ActionMenu
        name="Review"
        label="More actions"
        items={[
          { id: "send", label: "Send now", onAction: action },
          {
            id: "replace",
            label: "Replace saved lists",
            separatorBefore: true,
            danger: true,
            onAction: action,
          },
          { id: "clear", label: "Clear lists", danger: true, onAction: action },
        ]}
      />,
    ),
  );
  await click(document.querySelector('[aria-label="More actions"]')!);
  expect(
    [...document.querySelectorAll('[role="menuitem"]')].map((item) =>
      item.textContent?.trim(),
    ),
  ).toEqual(["Send now", "Replace saved lists", "Clear lists"]);
  expect(document.querySelectorAll('[role="separator"]')).toHaveLength(1);
  expect(
    document.querySelectorAll('[role="menuitem"].roster-action-danger'),
  ).toHaveLength(2);
  expect(action).not.toHaveBeenCalled();
  await click(
    [...document.querySelectorAll('[role="menuitem"]')].find(
      (item) => item.textContent === "Clear lists",
    )!,
  );
  expect(action).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});

// PhaseA conditional event reproduction. happy-dom has no layout or hit-testing.
// We explicitly retarget mouse pointer-up to an item after trigger-down opens it.
// This tests the handler invariant; it does NOT prove native menu-under-pointer
// geometry, real touch behavior, or the cause of the failed live gesture.
async function modalRows() {
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  history.replaceState({}, "", "/cwl/results?season=1");
  await act(async () =>
    root.render(
      <ActionPanel title="Synthetic Settings" trigger={null} onClose={() => {}}>
        <div className="rep-accounts roster-ui">
          {[0, 1, 2].map((group) => (
            <section key={group} aria-label={`Synthetic group ${group}`}>
              {[0, 1, 2].map((index) => {
                const row = group * 3 + index;
                return (
                  <div className="rep-account-row" key={row}>
                    <ActionMenu
                      name={`Synthetic account ${row}`}
                      items={[
                        { id: "edit", label: "Edit note", onAction: action },
                        {
                          id: "remove",
                          label: "Remove",
                          danger: true,
                          separatorBefore: true,
                          onAction: action,
                        },
                      ]}
                    />
                  </div>
                );
              })}
            </section>
          ))}
        </div>
      </ActionPanel>,
    ),
  );
}
async function pointer(
  target: Element,
  type: string,
  pointerType: "mouse" | "touch",
) {
  await act(async () => {
    target.dispatchEvent(
      new PointerEvent(type, {
        bubbles: true,
        cancelable: true,
        pointerType,
        pointerId: 23,
        isPrimary: true,
        button: 0,
        buttons: type === "pointerdown" ? 1 : 0,
        width: 6,
        height: 6,
        pressure: type === "pointerdown" ? 0.5 : 0,
        detail: 1,
      }),
    );
  });
}
async function pointerClick(target: Element, pointerType: "mouse" | "touch") {
  await pointer(target, "pointerdown", pointerType);
  await pointer(target, "pointerup", pointerType);
  await pointer(target, "click", pointerType);
}
const itemByText = (text: string) =>
  [...document.querySelectorAll<HTMLElement>('[role="menuitem"]')].find(
    (item) => item.textContent?.trim() === text,
  )!;
it.each([
  { row: 0, position: "first", target: "Edit note" },
  { row: 0, position: "first", target: "Remove" },
  { row: 8, position: "last", target: "Edit note" },
  { row: 8, position: "last", target: "Remove" },
])(
  "opening mouse gesture must not activate $position-row $target when its release is retargeted (geometry unproven)",
  async ({ row, position, target }) => {
    await modalRows();
    await pointer(trigger(`Synthetic account ${row}`), "pointerdown", "mouse");
    const item = itemByText(target);
    expect(item).toBeDefined();
    expect(document.querySelector("dialog[open]")!.contains(item)).toBe(true);
    expect(action).not.toHaveBeenCalled();
    // No click or second pointer-down is sent to the item.
    await pointer(item, "pointerup", "mouse");
    console.info(
      JSON.stringify({
        phase: "A",
        pointer: "mouse",
        position,
        retargetedRelease: target,
        actionCalls: action.mock.calls.length,
        geometry: "UNPROVEN",
      }),
    );
    expect(action).not.toHaveBeenCalled();
  },
);
it.each([0, 8])(
  "touch opening sequence for row %s keeps all actions untouched (unit events only)",
  async (row) => {
    await modalRows();
    const button = trigger(`Synthetic account ${row}`);
    await pointer(button, "pointerdown", "touch");
    // Public RAC opens on completed touch press, so no item exists to receive
    // the opening pointer-up. Unlike mouse, retargeting it would invent a target.
    expect(document.querySelector('[role="menu"]')).toBeNull();
    await pointer(button, "pointerup", "touch");
    await pointer(button, "click", "touch");
    expect(itemByText("Remove")).toBeDefined();
    expect(action).not.toHaveBeenCalled();
  },
);
it.each([
  { row: 0, pointerType: "mouse" as const },
  { row: 8, pointerType: "mouse" as const },
  { row: 0, pointerType: "touch" as const },
  { row: 8, pointerType: "touch" as const },
])(
  "explicit second $pointerType gesture still activates the row $row action once",
  async ({ row, pointerType }) => {
    await modalRows();
    await pointerClick(trigger(`Synthetic account ${row}`), pointerType);
    expect(action).not.toHaveBeenCalled();
    await pointerClick(itemByText("Remove"), pointerType);
    expect(action).toHaveBeenCalledTimes(1);
  },
);

it.each([
  { row: 0, pointerType: "mouse" as const },
  { row: 8, pointerType: "mouse" as const },
  { row: 0, pointerType: "touch" as const },
  { row: 8, pointerType: "touch" as const },
])(
  "opening $pointerType compatibility click cannot select row $row without a new press",
  async ({ row, pointerType }) => {
    await modalRows();
    await pointerClick(trigger(`Synthetic account ${row}`), pointerType);
    const item = itemByText("Remove");
    await pointer(item, "pointerup", pointerType);
    await pointer(item, "click", pointerType);
    expect(action).not.toHaveBeenCalled();
    expect(itemByText("Remove")).toBe(item);
    await pointerClick(item, pointerType);
    expect(action).toHaveBeenCalledTimes(1);
  },
);

async function key(target: Element, value: string, type = "keydown") {
  await act(async () =>
    target.dispatchEvent(
      new KeyboardEvent(type, { key: value, bubbles: true, cancelable: true }),
    ),
  );
}
it.each(["Enter", " "])(
  "keyboard %s opens and activates independently of pointer intent",
  async (value) => {
    await modalRows();
    const button = trigger("Synthetic account 8") as HTMLElement;
    await act(async () => button.focus());
    await key(button, value);
    await key(button, value, "keyup");
    expect(itemByText("Edit note")).toBeDefined();
    expect(action).not.toHaveBeenCalled();
    await key(document.activeElement!, "ArrowDown");
    const item = document.activeElement!;
    expect(item.getAttribute("role")).toBe("menuitem");
    await key(item, "Enter");
    await key(item, "Enter", "keyup");
    expect(action).toHaveBeenCalledTimes(1);
  },
);
it("virtual activation remains available after opening with a pointer", async () => {
  await modalRows();
  await pointerClick(trigger("Synthetic account 8"), "mouse");
  await act(async () => itemByText("Remove").click());
  expect(action).toHaveBeenCalledTimes(1);
});
it("virtual activation can open and select without pointer events", async () => {
  await modalRows();
  await act(async () =>
    (trigger("Synthetic account 0") as HTMLElement).click(),
  );
  expect(action).not.toHaveBeenCalled();
  await act(async () => itemByText("Edit note").click());
  expect(action).toHaveBeenCalledTimes(1);
});
it("cancelling the opening pointer closes and permits a fresh item gesture", async () => {
  await modalRows();
  const button = trigger("Synthetic account 8");
  await pointer(button, "pointerdown", "mouse");
  await pointer(button, "pointercancel", "mouse");
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(action).not.toHaveBeenCalled();
  await pointerClick(button, "touch");
  await pointerClick(itemByText("Edit note"), "touch");
  expect(action).toHaveBeenCalledTimes(1);
});
it("Escape clears a pending opening gesture and returns focus inside the modal", async () => {
  await modalRows();
  const button = trigger("Synthetic account 8");
  await pointerClick(button, "mouse");
  await key(document.querySelector('[role="menu"]')!, "Escape");
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect(document.querySelector("dialog[open]")).not.toBeNull();
  expect(document.activeElement).toBe(button);
  await act(async () => (button as HTMLElement).click());
  await act(async () => itemByText("Remove").click());
  expect(action).toHaveBeenCalledTimes(1);
});
it("switching menus and unmounting cannot retain another trigger's opening gesture", async () => {
  await pointer(trigger("One"), "pointerdown", "mouse");
  await pointerClick(trigger("Two"), "touch");
  await pointerClick(document.querySelector('[role="menuitem"]')!, "touch");
  expect(action).toHaveBeenCalledTimes(1);
  await pointer(trigger("One"), "pointerdown", "mouse");
  await act(async () =>
    root.render(
      <ActionMenu
        name="Replacement"
        items={[{ id: "edit", label: "Edit", onAction: action }]}
      />,
    ),
  );
  await click(trigger("Replacement"));
  await click(document.querySelector('[role="menuitem"]')!);
  expect(action).toHaveBeenCalledTimes(2);
});
it("disabling an open menu clears opening state and blocks activation", async () => {
  const renderMenu = (disabled: boolean) =>
    root.render(
      <ActionMenu
        name="Busy"
        disabled={disabled}
        items={[{ id: "edit", label: "Edit", onAction: action }]}
      />,
    );
  await act(async () => renderMenu(false));
  await pointerClick(trigger("Busy"), "mouse");
  await act(async () => renderMenu(true));
  expect(document.querySelector('[role="menu"]')).toBeNull();
  expect((trigger("Busy") as HTMLButtonElement).disabled).toBe(true);
  await act(async () => (trigger("Busy") as HTMLElement).click());
  expect(action).not.toHaveBeenCalled();
  await act(async () => renderMenu(false));
  await pointerClick(trigger("Busy"), "mouse");
  await pointerClick(document.querySelector('[role="menuitem"]')!, "mouse");
  expect(action).toHaveBeenCalledTimes(1);
});

it("blocks outside-ActionPanel opening-drag selection until a new press", async () => {
  await pointer(trigger("One"), "pointerdown", "mouse");
  expect(action).not.toHaveBeenCalled();
  const item = document.querySelector('[role="menuitem"]')!;
  expect(item.closest("dialog")).toBeNull();
  await pointer(item, "pointerup", "mouse");
  await pointer(item, "click", "mouse");
  expect(action).not.toHaveBeenCalled();
  expect(document.querySelector('[role="menu"]')).not.toBeNull();
  await pointerClick(item, "mouse");
  expect(action).toHaveBeenCalledTimes(1);
  expect(document.querySelector('[role="menu"]')).toBeNull();
});
