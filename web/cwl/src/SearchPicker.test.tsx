// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import SearchPicker, { filterOptions, type PickerOption } from "./SearchPicker";

const OPTIONS: PickerOption[] = [
  { value: "1", label: "General", detail: "Voice", icon: "🔊" },
  { value: "2", label: "Lounge", detail: "Voice", icon: "🔊" },
  {
    value: "3",
    label: "Clock EST",
    detail: "Times",
    icon: "🔊",
    disabledNote: "has a clock",
  },
];

let root: Root | undefined;
let host: HTMLDivElement;

function Harness({
  onChange,
  initial = "",
  clearable = false,
}: {
  onChange: (value: string) => void;
  initial?: string;
  clearable?: boolean;
}) {
  const [value, setValue] = useState(initial);
  return (
    <SearchPicker
      label="Voice channel"
      options={OPTIONS}
      value={value}
      placeholder="Select a voice channel"
      searchPlaceholder="Search voice channels"
      emptyText="No voice channels match."
      clearable={clearable}
      onChange={(next) => {
        onChange(next);
        setValue(next);
      }}
    />
  );
}

async function mount(node: React.ReactNode) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root!.render(node));
}

async function type(input: HTMLInputElement, text: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function key(input: HTMLInputElement, name: string) {
  await act(async () => {
    input.dispatchEvent(
      new KeyboardEvent("keydown", { key: name, bubbles: true }),
    );
  });
}

function phone(matches: boolean) {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  );
}

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  vi.unstubAllGlobals();
  document.body.innerHTML = "";
});

it("filters by every typed word in the name and detail", () => {
  expect(filterOptions(OPTIONS, "voice lou").map((o) => o.value)).toEqual([
    "2",
  ]);
  expect(filterOptions(OPTIONS, "  ")).toHaveLength(3);
});

it("desktop: opens under the field, selects with the keyboard, writes once", async () => {
  phone(false);
  const onChange = vi.fn();
  await mount(<Harness onChange={onChange} />);
  const trigger = host.querySelector<HTMLButtonElement>(
    ".search-picker-trigger",
  )!;
  expect(trigger.textContent).toContain("Select a voice channel");
  await act(async () => trigger.click());
  // Opening never writes.
  expect(onChange).not.toHaveBeenCalled();
  // Inline panel in the page, not a dialog.
  expect(host.querySelector(".search-picker-panel")).toBeTruthy();
  expect(document.querySelector("dialog")).toBeNull();
  const input = host.querySelector<HTMLInputElement>('input[role="combobox"]')!;
  expect(document.activeElement).toBe(input);
  await type(input, "lou");
  expect(
    Array.from(host.querySelectorAll('[role="option"]')).map(
      (node) => node.textContent,
    ),
  ).toEqual(["🔊LoungeVoice"]);
  await key(input, "Enter");
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith("2");
  expect(host.querySelector(".search-picker-panel")).toBeNull();
  expect(document.activeElement).toBe(trigger);
  expect(trigger.textContent).toContain("Lounge");
});

it("a row with a note cannot be selected, and Escape closes without a write", async () => {
  phone(false);
  const onChange = vi.fn();
  await mount(<Harness onChange={onChange} />);
  const trigger = host.querySelector<HTMLButtonElement>(
    ".search-picker-trigger",
  )!;
  await act(async () => trigger.click());
  const blocked = Array.from(host.querySelectorAll('[role="option"]')).find(
    (node) => node.textContent?.includes("Clock EST"),
  ) as HTMLElement;
  expect(blocked.getAttribute("aria-disabled")).toBe("true");
  expect(blocked.textContent).toContain("has a clock");
  await act(async () => blocked.click());
  expect(onChange).not.toHaveBeenCalled();
  const input = host.querySelector<HTMLInputElement>('input[role="combobox"]')!;
  await type(input, "zzz");
  expect(host.querySelector('[role="status"]')?.textContent).toBe(
    "No voice channels match.",
  );
  await key(input, "Escape");
  expect(onChange).not.toHaveBeenCalled();
  expect(host.querySelector(".search-picker-panel")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});

it("remove clears a clearable value", async () => {
  phone(false);
  const onChange = vi.fn();
  await mount(<Harness onChange={onChange} initial="1" clearable />);
  const remove = host.querySelector<HTMLButtonElement>(".search-picker-clear")!;
  expect(remove.getAttribute("aria-label")).toBe("Remove voice channel");
  await act(async () => remove.click());
  expect(onChange).toHaveBeenCalledWith("");
  expect(host.querySelector(".search-picker-clear")).toBeNull();
});

it("phone: opens a full-screen sheet with the search focused", async () => {
  phone(true);
  const showModal = vi.fn(function (this: HTMLDialogElement) {
    this.setAttribute("open", "");
  });
  const close = vi.fn(function (this: HTMLDialogElement) {
    this.removeAttribute("open");
  });
  Object.assign(HTMLDialogElement.prototype, { showModal, close });
  const onChange = vi.fn();
  await mount(<Harness onChange={onChange} />);
  const trigger = host.querySelector<HTMLButtonElement>(
    ".search-picker-trigger",
  )!;
  expect(trigger.getAttribute("aria-haspopup")).toBe("dialog");
  // No inline panel on a phone.
  await act(async () => trigger.click());
  expect(host.querySelector(".search-picker-panel")).toBeNull();
  const sheet = document.querySelector<HTMLDialogElement>(
    "dialog.search-picker-sheet",
  )!;
  expect(showModal).toHaveBeenCalledTimes(1);
  expect(sheet.textContent).toContain("Voice channel");
  const input = sheet.querySelector<HTMLInputElement>(
    'input[role="combobox"]',
  )!;
  expect(document.activeElement).toBe(input);
  const general = Array.from(sheet.querySelectorAll('[role="option"]')).find(
    (node) => node.textContent?.includes("General"),
  ) as HTMLElement;
  vi.useFakeTimers();
  await act(async () => general.click());
  // A quick second tap still lands on the sheet and writes nothing more.
  await act(async () => general.click());
  expect(onChange).toHaveBeenCalledTimes(1);
  expect(onChange).toHaveBeenCalledWith("1");
  expect(close).not.toHaveBeenCalled();
  await act(async () => {
    vi.advanceTimersByTime(300);
  });
  vi.useRealTimers();
  expect(close).toHaveBeenCalled();
  expect(sheet.querySelectorAll('[role="option"]')).toHaveLength(0);
});

it("phone: back or Escape on the sheet does not close a dialog around it", async () => {
  phone(true);
  Object.assign(HTMLDialogElement.prototype, {
    showModal(this: HTMLDialogElement) {
      this.setAttribute("open", "");
    },
    close(this: HTMLDialogElement) {
      this.removeAttribute("open");
    },
  });
  const outerCancel = vi.fn();
  const onChange = vi.fn();
  await mount(
    <dialog open onCancel={outerCancel}>
      <Harness onChange={onChange} />
    </dialog>,
  );
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".search-picker-trigger")!.click(),
  );
  const sheet = document.querySelector<HTMLDialogElement>(
    "dialog.search-picker-sheet",
  )!;
  expect(sheet.hasAttribute("open")).toBe(true);
  await act(async () => {
    sheet.dispatchEvent(new Event("cancel", { cancelable: true }));
  });
  expect(outerCancel).not.toHaveBeenCalled();
  expect(onChange).not.toHaveBeenCalled();
  expect(sheet.hasAttribute("open")).toBe(false);
});

it("picking the current value closes without a write, like a native select", async () => {
  phone(false);
  const onChange = vi.fn();
  await mount(<Harness onChange={onChange} initial="2" />);
  const trigger = host.querySelector<HTMLButtonElement>(
    ".search-picker-trigger",
  )!;
  await act(async () => trigger.click());
  const current = Array.from(host.querySelectorAll('[role="option"]')).find(
    (node) => node.getAttribute("aria-selected") === "true",
  ) as HTMLElement;
  expect(current.textContent).toContain("Lounge");
  await act(async () => current.click());
  expect(onChange).not.toHaveBeenCalled();
  expect(host.querySelector(".search-picker-panel")).toBeNull();
  expect(document.activeElement).toBe(trigger);
});
