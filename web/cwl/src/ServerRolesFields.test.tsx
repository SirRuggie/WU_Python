// @vitest-environment happy-dom
import { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it } from "vitest";
import ServerRolesFields from "./ServerRolesFields";
import type { ManagementField } from "./serverManagement";
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
const initial = [
  {
    role_id: "44",
    label: "Base Builder",
    short_line: "Design bases",
    order: 0,
  },
  {
    role_id: "55",
    label: "VC Participant",
    short_line: "Join voice",
    order: 1,
  },
];
const field: ManagementField = {
  key: "roles",
  label: "Server roles",
  type: "server_roles",
  value: "[]",
  options: [
    { value: "44", label: "Builder", color: 0x123456 },
    { value: "55", label: "Voice", color: 0x654321 },
  ],
};
function Sample({
  empty = false,
  documentField = field,
}: {
  empty?: boolean;
  documentField?: ManagementField;
}) {
  const [value, setValue] = useState(JSON.stringify(empty ? [] : initial));
  return (
    <>
      <ServerRolesFields
        field={documentField}
        value={value}
        onChange={setValue}
        disabled={false}
      />
      <output>{value}</output>
    </>
  );
}
it("shows counters and changes order/removal only in draft", async () => {
  await act(async () => root.render(<Sample />));
  expect(host.textContent).toContain("2 of 25 roles");
  expect(host.textContent).toContain("12/40");
  const up = host.querySelector(
    '[aria-label="Move VC Participant up"]',
  ) as HTMLButtonElement;
  await act(async () => up.click());
  let rows = JSON.parse(host.querySelector("output")!.textContent!);
  expect(rows.map((row: { role_id: string }) => row.role_id)).toEqual([
    "55",
    "44",
  ]);
  expect(rows.map((row: { order: number }) => row.order)).toEqual([0, 1]);
  await act(async () =>
    (
      host.querySelector('[aria-label="Remove Voice"]') as HTMLButtonElement
    ).click(),
  );
  rows = JSON.parse(host.querySelector("output")!.textContent!);
  expect(rows).toEqual([initial[0]]);
  expect(host.querySelectorAll('input[name][autocomplete="off"]')).toHaveLength(
    2,
  );
});
it("distinguishes the empty state with a visible Add role control", async () => {
  await act(async () => root.render(<Sample empty />));
  expect(host.textContent).toContain(
    "No server roles yet. Add a role to show it in Roles and clan links.",
  );
  expect(host.textContent).toContain("Add role");
  expect(host.querySelectorAll("input")).toHaveLength(0);
});

it("retains a legacy duplicate row with the exact explanation and inline save error", async () => {
  await act(async () =>
    root.render(
      <Sample
        documentField={{
          ...field,
          role_conflicts: ["44"],
          error: "This role is already used for a Town Hall.",
        }}
      />,
    ),
  );
  expect(host.textContent).toContain(
    "Also used for a Town Hall. Remove it from one list.",
  );
  expect(host.querySelector('[role="alert"]')?.textContent).toBe(
    "This role is already used for a Town Hall.",
  );
  expect(JSON.parse(host.querySelector("output")!.textContent!)).toHaveLength(
    2,
  );
});
