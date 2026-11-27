// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Records from "./TownHallRecords";
import type { ManagementSection } from "./serverManagement";
import {
  clickOption,
  openPicker,
  pickerByLabel,
} from "./searchPickerTestUtils";

const records: ManagementSection[] = [
  {
    id: "add",
    label: "Add Town Hall",
    description: "",
    group: "",
    endpoint: "/manage/town-halls/add",
    list_role: "add",
  },
  {
    id: "settings",
    label: "Lowest FWA Town Hall",
    description: "",
    group: "",
    endpoint: "/manage/town-halls/settings",
    list_role: "setting",
    value: "TH12",
  },
  {
    id: "19",
    label: "Town Hall 19",
    description: "",
    group: "",
    endpoint: "/manage/town-halls/19",
    list_role: "level",
    list_group: "fwa",
    meta: "No weight range",
  },
  {
    id: "12",
    label: "Town Hall 12",
    description: "",
    group: "",
    endpoint: "/manage/town-halls/12",
    list_role: "level",
    list_group: "fwa",
    meta: "111k – 120k",
  },
  {
    id: "11",
    label: "Town Hall 11",
    description: "",
    group: "",
    endpoint: "/manage/town-halls/11",
    list_role: "level",
    list_group: "other",
  },
];
let root: Root;
let host: HTMLDivElement;
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

it("puts Add first, retains the setting value, and closes Other levels by default", async () => {
  const open = vi.fn();
  await act(async () =>
    root.render(
      <Records records={records} mayLeave={() => true} open={open} />,
    ),
  );
  expect(host.querySelector("a")?.textContent).toBe("Add Town Hall");
  expect(host.querySelector(".town-hall-setting")?.textContent).toContain(
    "TH12",
  );
  expect(
    [...host.querySelectorAll(".town-hall-record")].map(
      (node) => node.textContent,
    ),
  ).toEqual([
    "TH 19Town Hall 19No roleNo weight range",
    "TH 12Town Hall 12No role111k – 120k",
    "TH 11Town Hall 11No role",
  ]);
  expect(host.querySelector("details")!.open).toBe(false);
  expect(host.querySelector("summary")!.textContent).toBe("Other levels (1)");
  expect(host.querySelector(".town-hall-no-weight")!.textContent).toBe(
    "No weight range",
  );
  await act(async () =>
    host.querySelector<HTMLAnchorElement>(".town-hall-record")!.click(),
  );
  expect(open).toHaveBeenCalledWith("/manage/town-halls/19");
});

it("uses a compact switcher and gates both switch and back through mayLeave", async () => {
  const open = vi.fn(),
    mayLeave = vi.fn().mockReturnValue(false);
  await act(async () =>
    root.render(
      <Records
        records={records}
        currentEndpoint="/manage/town-halls/19"
        editor
        mayLeave={mayLeave}
        open={open}
      />,
    ),
  );
  expect(host.querySelector("details")).toBeNull();
  await act(async () => host.querySelector<HTMLAnchorElement>("a")!.click());
  expect(mayLeave).toHaveBeenCalledTimes(1);
  expect(open).not.toHaveBeenCalled();
  mayLeave.mockReturnValue(true);
  const picker = pickerByLabel(host, "Town Hall");
  await openPicker(picker);
  await clickOption(picker, "Town Hall 12");
  expect(open).toHaveBeenCalledWith("/manage/town-halls/12");
  await act(async () => host.querySelector<HTMLAnchorElement>("a")!.click());
  expect(open).toHaveBeenCalledWith("/manage/town-halls");
});

it.each([
  { ctrlKey: true },
  { metaKey: true },
  { shiftKey: true },
  { altKey: true },
  { button: 1 },
])(
  "preserves native modified or nonprimary anchor navigation: %j",
  async (options) => {
    const open = vi.fn(),
      mayLeave = vi.fn().mockReturnValue(false);
    await act(async () =>
      root.render(
        <Records records={records} mayLeave={mayLeave} open={open} />,
      ),
    );
    const link = host.querySelector<HTMLAnchorElement>(".town-hall-record")!;
    const event = new MouseEvent("click", {
      bubbles: true,
      cancelable: true,
      button: 0,
      ...options,
    });
    await act(async () => {
      link.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(false);
    expect(mayLeave).not.toHaveBeenCalled();
    expect(open).not.toHaveBeenCalled();
    expect(link.getAttribute("href")).toBe("/manage/town-halls/19");
  },
);
