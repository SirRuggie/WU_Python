// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, expect, it, vi } from "vitest";
import RolePicker from "./RolePicker";
import {
  openPicker,
  optionTexts,
  pickOption,
  pickerValue,
  typeInPicker,
} from "./searchPickerTestUtils";

const ROLES = [
  { id: "1", name: "Leaders", color: 0xff0000 },
  { id: "2", name: "Bot role", managed: true },
  { id: "3", name: "Members" },
  { id: "4", name: "Elders" },
];
let root: Root | undefined;
let host: HTMLDivElement;

async function mount(onChoose = vi.fn(), selected = ["3"]) {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root!.render(
      <RolePicker
        roles={ROLES}
        selected={selected}
        disabled={false}
        label="Ignored roles"
        onChoose={onChoose}
      />,
    ),
  );
  return host.querySelector<HTMLElement>(".search-picker")!;
}

afterEach(async () => {
  if (root) await act(async () => root!.unmount());
  host?.remove();
  root = undefined;
});

it("lists roles in server order without managed or selected ones", async () => {
  const picker = await mount();
  expect(pickerValue(picker)).toBe("Add a role");
  await openPicker(picker);
  expect(optionTexts(picker)).toEqual(["Leaders", "Elders"]);
  await typeInPicker(picker, "eld");
  expect(optionTexts(picker)).toEqual(["Elders"]);
});

it("adds the chosen role through onChoose and stays empty", async () => {
  const onChoose = vi.fn();
  const picker = await mount(onChoose);
  await pickOption(picker, "Elders");
  expect(onChoose).toHaveBeenCalledTimes(1);
  expect(onChoose).toHaveBeenCalledWith(ROLES[3]);
  expect(pickerValue(picker)).toBe("Add a role");
});
