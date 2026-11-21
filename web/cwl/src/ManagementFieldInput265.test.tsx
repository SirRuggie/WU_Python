// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import Field from "./ManagementFieldInput";
import {
  fieldError,
  type ManagementField,
  type ManagementValue,
} from "./serverManagement";
import {
  openPicker,
  pickOption,
  pickerByLabel,
  pickerValue,
  typeInPicker,
  optionTexts,
  clearPicker,
} from "./searchPickerTestUtils";
const CHANNEL_A = "111111111111111111",
  CHANNEL_B = "222222222222222222";
const ROLE_A = "333333333333333333",
  ROLE_B = "444444444444444444",
  UNKNOWN = "999999999999999999";
const channels = [
  { value: CHANNEL_A, label: "#announcements", type: 5 },
  { value: CHANNEL_B, label: "#staff", type: 0 },
];
const roles = [
  { value: ROLE_A, label: "Recruiters" },
  { value: ROLE_B, label: "Helpers" },
];
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const changes = vi.fn();
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
  changes.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function mount(field: ManagementField, disabled = false) {
  function Controlled() {
    const [value, setValue] = useState(field.value);
    return (
      <Field
        field={field}
        value={value}
        disabled={disabled}
        revision="r265"
        onChange={(next) => {
          changes(next);
          setValue(next);
        }}
      />
    );
  }
  await act(async () => root.render(<Controlled />));
}
it.each([
  "desk_channel_id",
  "desk_staff_parent",
  "main_candidate_parent",
  "main_staff_parent",
  "fwa_candidate_parent",
  "fwa_staff_parent",
  "console_channel",
])(
  "uses one shared channel control for %s and resets search for reselection",
  async (key) => {
    await mount({
      key,
      label: "Channel",
      type: "channel",
      value: CHANNEL_A,
      options: channels,
      description: "Existing help",
      required: true,
    });
    const picker = pickerByLabel(host, "Channel *");
    expect(host.querySelector("select")).toBeNull();
    expect(host.querySelector("input")).toBeNull();
    expect(
      host
        .querySelector(`#manage-${key.replaceAll("_", "-")}`)
        ?.getAttribute("aria-describedby"),
    ).toBe(`manage-${key.replaceAll("_", "-")}-help`);
    expect(pickerValue(picker)).toBe("#announcements");
    await pickOption(picker, "#staff", "staff");
    expect(changes).toHaveBeenLastCalledWith(CHANNEL_B);
    expect(pickerValue(picker)).toBe("#staff");
    await openPicker(picker);
    expect(
      picker.querySelector<HTMLInputElement>('input[role="combobox"]')?.value,
    ).toBe("");
    await typeInPicker(picker, "announce");
    expect(optionTexts(picker)).toEqual(["#announcements"]);
    await act(async () =>
      picker.querySelector<HTMLElement>('[role="option"]')!.click(),
    );
    expect(changes).toHaveBeenLastCalledWith(CHANNEL_A);
    expect(host.textContent).not.toMatch(/\d{15}/);
  },
);
it("preserves explicit channel types and every supplied allowed option", async () => {
  await mount({
    key: "channel",
    label: "Channel",
    type: "select",
    source: "channels",
    value: "",
    options: [
      { value: "category", label: "General", type: 4 },
      { value: "forum", label: "#Forum", type: 15 },
      { value: "post", label: "#Post", type: 11 },
    ],
  });
  const picker = pickerByLabel(host, "Channel");
  await openPicker(picker);
  expect(optionTexts(picker)).toEqual([
    "General",
    "#ForumForum",
    "#PostForum post",
  ]);
});
it.each([
  "account_thread_recruiter_role",
  "staff_thread_recruiter_role",
  "main_thread_recruiter_role",
  "fwa_thread_recruiter_role",
])(
  "reuses scalar RoleSelect for %s with only string IDs in the draft",
  async (key) => {
    await mount({
      key,
      label: "Role",
      type: "role",
      value: ROLE_A,
      options: roles,
    });
    const picker = pickerByLabel(host, "Role");
    await pickOption(picker, "Helpers", "Help");
    expect(changes).toHaveBeenLastCalledWith(ROLE_B);
    expect(pickerValue(picker)).toBe("Helpers");
    await openPicker(picker);
    expect(optionTexts(picker)).toEqual(["Recruiters", "Helpers"]);
    expect(host.querySelector("select")).toBeNull();
    expect(host.textContent).not.toMatch(/\d{15}/);
  },
);
it("keeps unavailable scalar selections name-only, with existing clear/required validation", async () => {
  const field: ManagementField = {
    key: "role",
    label: "Role",
    type: "role",
    value: UNKNOWN,
    options: [],
    required: true,
  };
  await mount(field);
  const picker = pickerByLabel(host, "Role *");
  expect(pickerValue(picker)).toBe("Unavailable role");
  expect(changes).not.toHaveBeenCalled();
  expect(host.textContent).not.toContain(UNKNOWN);
  await clearPicker(picker);
  expect(changes).toHaveBeenCalledWith("");
  expect(fieldError(field, "")).toBe("Role is required.");
});
it("retains unknown and hidden multi-role IDs in order until an explicit named removal", async () => {
  await mount({
    key: "ticket_staff_viewer_role_ids",
    label: "Viewer roles",
    type: "multiselect",
    source: "roles",
    value: [UNKNOWN, ROLE_A],
    options: roles,
  });
  const picker = pickerByLabel(host, "Viewer roles");
  expect(host.textContent).toContain("Unavailable role");
  expect(host.textContent).toContain("Recruiters");
  expect(host.textContent).not.toMatch(/\d{15}/);
  await pickOption(picker, "Helpers", "Helpers");
  expect(changes).toHaveBeenLastCalledWith([UNKNOWN, ROLE_A, ROLE_B]);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="Remove Recruiters"]')!
      .click(),
  );
  expect(changes).toHaveBeenLastCalledWith([UNKNOWN, ROLE_B]);
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Remove Unavailable role 1"]',
      )!
      .click(),
  );
  expect(changes).toHaveBeenLastCalledWith([ROLE_B]);
});
it("preserves selected arrays when options refresh and applies no managed-role policy to generic choices", async () => {
  const selected: ManagementValue = [UNKNOWN, ROLE_A];
  const onChange = vi.fn();
  const field: ManagementField = {
    key: "roles",
    label: "Roles",
    type: "multiselect",
    source: "roles",
    value: selected,
    options: roles,
  };
  await act(async () =>
    root.render(
      <Field
        field={field}
        value={selected}
        disabled={false}
        revision={1}
        onChange={onChange}
      />,
    ),
  );
  await act(async () =>
    root.render(
      <Field
        field={{ ...field, options: [roles[1]] }}
        value={selected}
        disabled={false}
        revision={2}
        onChange={onChange}
      />,
    ),
  );
  expect(onChange).not.toHaveBeenCalled();
  expect(host.querySelectorAll(".manage-selected-roles li")).toHaveLength(2);
  await pickOption(pickerByLabel(host, "Roles"), "Helpers");
  expect(onChange).toHaveBeenCalledWith([UNKNOWN, ROLE_A, ROLE_B]);
});
it.each(["readonly", "busy"])(
  "keeps %s fields blocked without dropping unavailable values",
  async (mode) => {
    await mount(
      {
        key: "role",
        label: "Role",
        type: "multiselect",
        source: "roles",
        value: [UNKNOWN],
        options: roles,
        readonly: mode === "readonly",
      },
      mode === "busy",
    );
    expect(
      [...host.querySelectorAll<HTMLButtonElement>("button")].every(
        (button) => button.disabled,
      ),
    ).toBe(true);
    expect(changes).not.toHaveBeenCalled();
    expect(host.textContent).not.toContain(UNKNOWN);
  },
);
it("keeps multiple channels and unrelated multiselects on their original array path", async () => {
  await mount({
    key: "channels",
    label: "Channels",
    type: "multiselect",
    source: "channels",
    value: [CHANNEL_A],
    options: channels,
  });
  expect(host.querySelector(".search-picker")).toBeNull();
  expect(
    host.querySelector<HTMLInputElement>('input[type="checkbox"]')?.checked,
  ).toBe(true);
  await act(async () =>
    host
      .querySelectorAll<HTMLInputElement>('input[type="checkbox"]')[1]
      .click(),
  );
  expect(changes).toHaveBeenLastCalledWith([CHANNEL_A, CHANNEL_B]);
});
