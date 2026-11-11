// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import ChannelCombobox from "./ChannelCombobox";
import {
  clearPicker,
  openPicker,
  optionTexts,
  pickOption,
  pickerValue,
  typeInPicker,
} from "./searchPickerTestUtils";

const CHANNELS = [
  { id: "111111111111111111", name: "General", type: 4 },
  { id: "222222222222222222", name: "alerts", type: 0 },
  { id: "333333333333333333", name: "Raid thread", type: 11 },
];
let root: Root | undefined;
let host: HTMLDivElement;
const onChange = vi.fn();
const onResolve = vi.fn();

async function mount(value = "", withResolve = true) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root!.render(
      <ChannelCombobox
        label="Channel"
        channels={CHANNELS}
        value={value}
        disabled={false}
        onChange={onChange}
        onResolve={withResolve ? onResolve : undefined}
      />,
    ),
  );
  return host.querySelector<HTMLElement>(".search-picker")!;
}

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
  onChange.mockReset();
  onResolve.mockReset();
});

it("shows names only: no # on a category, a type word, never an ID", async () => {
  const picker = await mount();
  await openPicker(picker);
  expect(optionTexts(picker)).toEqual([
    "General",
    "#alerts",
    "#Raid threadForum post",
  ]);
  expect(host.textContent).not.toMatch(/\d{15}/);
});

it("finds a channel by a pasted ID without showing the ID", async () => {
  const picker = await mount();
  await openPicker(picker);
  await typeInPicker(picker, "222222222222222222");
  expect(optionTexts(picker)).toEqual(["#alerts"]);
  expect(picker.textContent).not.toContain("222222222222222222");
});

it("offers a lookup row for an unknown ID and calls onResolve, not onChange", async () => {
  const picker = await mount();
  await pickOption(
    picker,
    "Look up channel or forum post ID",
    "999999999999999999",
  );
  expect(onResolve).toHaveBeenCalledWith("999999999999999999");
  expect(onChange).not.toHaveBeenCalled();
});

it("looks up a saved but hidden post when its own ID is pasted", async () => {
  const picker = await mount("999999999999999999");
  expect(pickerValue(picker)).toContain("Selected channel unavailable");
  await pickOption(
    picker,
    "Look up channel or forum post ID",
    "999999999999999999",
  );
  expect(onResolve).toHaveBeenCalledWith("999999999999999999");
  expect(onChange).not.toHaveBeenCalled();
});

it("has no lookup row without onResolve", async () => {
  const picker = await mount("", false);
  await openPicker(picker);
  await typeInPicker(picker, "999999999999999999");
  expect(optionTexts(picker)).toEqual([]);
  expect(onResolve).not.toHaveBeenCalled();
});

it("selects, clears, and names a missing value without its ID", async () => {
  let picker = await mount("222222222222222222");
  expect(pickerValue(picker)).toBe("#alerts");
  await clearPicker(picker);
  expect(onChange).toHaveBeenLastCalledWith("");
  await act(async () => root!.unmount());
  host.remove();
  picker = await mount("444444444444444444");
  expect(pickerValue(picker)).toBe("Selected channel unavailable");
  expect(host.textContent).not.toContain("444444444444444444");
  await pickOption(picker, "General");
  expect(onChange).toHaveBeenLastCalledWith("111111111111111111");
});
