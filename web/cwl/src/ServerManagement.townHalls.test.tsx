// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServerManagement from "./ServerManagement";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
const section = {
  id: "town_halls",
  label: "Town Halls",
  endpoint: "/manage/town-halls",
  allowed: true,
};
const records = [
  {
    id: "add",
    label: "Add Town Hall",
    endpoint: "/manage/town-halls/add",
    list_role: "add",
  },
  {
    id: "settings",
    label: "Lowest FWA Town Hall",
    endpoint: "/manage/town-halls/settings",
    list_role: "setting",
    value: "TH12",
  },
  {
    id: "19",
    label: "Town Hall 19",
    endpoint: "/manage/town-halls/19",
    list_role: "level",
    list_group: "fwa",
    meta: "181k – 190k",
  },
];
const level = (n: number) => ({
  ...section,
  endpoint: `/manage/town-halls/${n}`,
  label: `Town Hall ${n}`,
  level: n,
  revision: 7,
  documents: records,
  fields: [
    {
      key: "emoji",
      label: "Town Hall emoji",
      value: "",
      type: "emoji",
      group: "Town Hall",
    },
    {
      key: "min",
      label: "Minimum weight",
      value: 181000,
      type: "number",
      group: "Town Hall",
    },
    {
      key: "max",
      label: "Maximum weight",
      value: 190000,
      type: "number",
      group: "Town Hall",
    },
  ],
});
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  transport.mockReset();
  transport.mockImplementation(async (path, method) => {
    if (path === "/manage") return { sections: [section] };
    if (path === "/manage/town-halls/emojis") return { emojis: [], errors: {} };
    if (method === "PATCH") return { ...level(20), revision: 8, saved: true };
    if (path === "/manage/town-halls/add")
      return {
        ...section,
        endpoint: path,
        revision: 7,
        create: true,
        submit_label: "Add Town Hall",
        documents: records,
        fields: [
          {
            key: "level",
            label: "Town Hall level",
            value: 20,
            type: "number",
            required: true,
          },
          { key: "emoji", label: "Town Hall emoji", value: "", type: "emoji" },
        ],
      };
    if (path === "/manage/town-halls/19") return level(19);
    return {
      ...section,
      endpoint: undefined,
      revision: 7,
      documents: records,
      fields: [],
    };
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
function Fixture({ initial }: { initial: string }) {
  const [path, setPath] = useState(initial);
  return (
    <ServerManagement
      area="fwa-settings"
      townHallPath={path}
      onTownHallNavigate={setPath}
    />
  );
}
it("opens a deep-linked grouped editor rather than treating its documents as the list", async () => {
  await act(async () =>
    root.render(<Fixture initial="/manage/town-halls/19" />),
  );
  expect(host.querySelector("h1")?.textContent).toBe("Town Hall 19");
  expect(host.querySelector("legend")?.textContent).toContain("Town Hall");
  expect(host.querySelector("#manage-min")).not.toBeNull();
  expect(host.querySelector(".town-hall-switcher")).not.toBeNull();
});
it("shows grouped list even with fewer than eight records", async () => {
  await act(async () => root.render(<Fixture initial="/manage/town-halls" />));
  expect(host.querySelector(".town-hall-records")).not.toBeNull();
  expect(host.querySelector(".town-hall-add")?.textContent).toBe(
    "Add Town Hall",
  );
  expect(host.querySelector("form")).toBeNull();
});
it("explicit Add sends every displayed field and opens the saved level", async () => {
  await act(async () =>
    root.render(<Fixture initial="/manage/town-halls/add" />),
  );
  const submit = host.querySelector<HTMLButtonElement>(
    'button[type="submit"]',
  )!;
  expect(submit.disabled).toBe(false);
  await act(async () => submit.click());
  const call = transport.mock.calls.find(([, method]) => method === "PATCH")!;
  expect(call[0]).toBe("/manage/town-halls/add");
  expect(call[2].values).toEqual({ level: 20, emoji: "" });
  expect(host.querySelector("h1")?.textContent).toBe("Town Hall 20");
  expect(host.textContent).toContain("Saved.");
});

it("keeps the role draft after an unknown second CAS outcome without retrying", async () => {
  const { pickerByLabel, openPicker, clickOption, pickerValue } =
    await import("./searchPickerTestUtils");
  const original = {
    ...level(19),
    role_revision: 0,
    fields: [
      level(19).fields[0],
      {
        key: "role",
        label: "Discord role",
        type: "role",
        value: "17",
        group: "Town Hall",
        options: [
          { value: "17", label: "TH17" },
          { value: "19", label: "TH19" },
        ],
      },
      ...level(19).fields.slice(1),
    ],
  };
  transport.mockImplementation(async (path, method) => {
    if (path === "/manage") return { sections: [section] };
    if (path === "/manage/town-halls/19") {
      if (method === "PATCH")
        return {
          ...original,
          revision: 8,
          saved: true,
          partial_result: {
            registry_saved: true,
            role_saved: null,
            role_outcome: "unknown",
            role_error:
              "Town Hall fields saved. The role save could not be confirmed. Refresh and review your role edit.",
          },
        };
      return original;
    }
    return { emojis: [], errors: {} };
  });
  await act(async () =>
    root.render(<Fixture initial="/manage/town-halls/19" />),
  );
  const picker = pickerByLabel(host, "Discord role");
  await openPicker(picker);
  await clickOption(picker, "TH19");
  await act(async () =>
    host.querySelector<HTMLButtonElement>('button[type="submit"]')!.click(),
  );
  expect(
    transport.mock.calls.filter(([, method]) => method === "PATCH"),
  ).toHaveLength(1);
  expect(pickerValue(pickerByLabel(host, "Discord role"))).toContain("TH19");
  expect(host.textContent).toContain("could not be confirmed");
  expect(host.textContent).not.toContain("Saved.");
  expect(
    host.querySelector<HTMLButtonElement>('button[type="submit"]')!.disabled,
  ).toBe(true);
});
