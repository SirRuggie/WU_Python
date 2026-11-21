// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServerManagement from "./ServerManagement";
import { ApiError } from "./api";
import {
  pickerByLabel,
  pickOption,
  pickerValue,
} from "./searchPickerTestUtils";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
const A = "111111111111111111",
  B = "222222222222222222",
  R = "333333333333333333",
  S = "444444444444444444",
  UNKNOWN = "999999999999999999";
const catalog = {
  id: "ticket_settings",
  label: "Ticket settings",
  description: "Channels and roles",
  group: "Recruitment",
  allowed: true,
  endpoint: "/manage/ticket-settings",
};
const fields = [
  {
    key: "desk_channel_id",
    label: "Warrior Desk channel",
    type: "channel",
    value: A,
  },
  {
    key: "desk_staff_parent",
    label: "Staff thread channel",
    type: "channel",
    value: B,
  },
  {
    key: "account_thread_recruiter_role",
    label: "Add account staff role",
    type: "role",
    value: R,
  },
  {
    key: "staff_thread_recruiter_role",
    label: "Contact staff role",
    type: "role",
    value: S,
  },
];
const choices = {
  channels: [
    { value: A, label: "#warrior-desk", type: 0 },
    { value: B, label: "#staff", type: 0 },
  ],
  roles: [
    { value: R, label: "Account staff" },
    { value: S, label: "Contact staff" },
  ],
};
let host: HTMLDivElement,
  root: ReturnType<typeof createRoot>,
  conflict: boolean;
const button = (text: string) =>
  [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) =>
      b.textContent?.trim() === text ||
      b.textContent?.startsWith(text + "Channels"),
  )!;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  window.matchMedia = vi.fn().mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  conflict = false;
  transport.mockReset();
  transport.mockImplementation(
    async (
      path: string,
      method?: string,
      body?: { values: Record<string, unknown> },
    ) => {
      if (path === "/manage") return { sections: [catalog] };
      if (path === "/manage/choices") return choices;
      if (path === "/manage/ticket-settings")
        return {
          ...catalog,
          revision: "r265",
          fields: [],
          documents: [
            {
              id: "desk",
              label: "Warrior Desk",
              endpoint: "/manage/ticket-settings/desk",
            },
            {
              id: "viewers",
              label: "Staff viewing access",
              endpoint: "/manage/ticket-settings/viewers",
            },
          ],
        };
      if (path === "/manage/ticket-settings/desk") {
        if (method && conflict)
          throw new ApiError("Settings changed. Reload before saving.", 409);
        return {
          ...catalog,
          revision: method ? "r266" : "r265",
          fields: fields.map((field) => ({
            ...field,
            value: body?.values[field.key] ?? field.value,
          })),
          desk_readiness: { ready: true, live: false, missing: [] },
        };
      }
      if (path === "/manage/ticket-settings/viewers")
        return {
          ...catalog,
          revision: method ? "r266" : "r265",
          fields: [
            {
              key: "ticket_staff_viewer_role_ids",
              label: "Extra staff viewer roles",
              type: "multiselect",
              source: "roles",
              value: body?.values.ticket_staff_viewer_role_ids ?? [UNKNOWN, R],
            },
          ],
        };
      throw new Error(`Unlisted fixture ${path}`);
    },
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function openDesk() {
  await act(async () =>
    root.render(<ServerManagement area="applications-settings" />),
  );
  const item = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.startsWith("Warrior Desk"),
  )!;
  await act(async () => item.click());
}
it("keeps picker changes local until explicit Save and preserves the exact revision/value/request-ID path", async () => {
  await openDesk();
  expect(host.querySelectorAll(".search-picker")).toHaveLength(4);
  expect(host.querySelector("select")).toBeNull();
  expect(transport.mock.calls.map(([path]) => path)).toEqual([
    "/manage",
    "/manage/ticket-settings/desk",
    "/manage/choices",
  ]);
  await pickOption(
    pickerByLabel(host, "Warrior Desk channel"),
    "#staff",
    "staff",
  );
  await pickOption(
    pickerByLabel(host, "Add account staff role"),
    "Contact staff",
    "Contact",
  );
  expect(transport.mock.calls.filter(([, method]) => method)).toHaveLength(0);
  await act(async () => {
    button("Save changes").click();
    button("Save changes").click();
  });
  const writes = transport.mock.calls.filter(([, method]) => method);
  expect(writes).toHaveLength(1);
  expect(writes[0].slice(0, 2)).toEqual([
    "/manage/ticket-settings/desk",
    "PATCH",
  ]);
  expect(writes[0][2]).toEqual({
    revision: "r265",
    values: { desk_channel_id: B, account_thread_recruiter_role: S },
    request_id: expect.any(String),
  });
  expect(host.textContent).not.toMatch(/\d{15}/);
});
it("keeps the named draft on conflict and blocks a duplicate overwrite", async () => {
  await openDesk();
  await pickOption(
    pickerByLabel(host, "Add account staff role"),
    "Contact staff",
  );
  conflict = true;
  await act(async () => button("Save changes").click());
  expect(pickerValue(pickerByLabel(host, "Add account staff role"))).toContain(
    "Contact staff",
  );
  expect(host.textContent).toContain(
    "Someone changed these settings. Your edits are still here.",
  );
  expect(button("Save changes").disabled).toBe(true);
  expect(transport.mock.calls.filter(([, method]) => method)).toHaveLength(1);
});
it("preserves viewer-role array IDs/order and unknown selections through the existing Save endpoint", async () => {
  await act(async () =>
    root.render(<ServerManagement area="applications-settings" />),
  );
  const settings = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.startsWith("Ticket settings"),
  )!;
  await act(async () => settings.click());
  const viewers = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.includes("Staff viewing access"),
  )!;
  await act(async () => viewers.click());
  expect(host.textContent).toContain("Unavailable role");
  await pickOption(
    pickerByLabel(host, "Extra staff viewer roles"),
    "Contact staff",
  );
  expect(transport.mock.calls.filter(([, method]) => method)).toHaveLength(0);
  await act(async () => button("Save changes").click());
  const writes = transport.mock.calls.filter(([, method]) => method);
  expect(writes).toHaveLength(1);
  expect(writes[0][0]).toBe("/manage/ticket-settings/viewers");
  expect(writes[0][2]).toEqual({
    revision: "r265",
    values: { ticket_staff_viewer_role_ids: [UNKNOWN, R, S] },
    request_id: expect.any(String),
  });
  expect(host.textContent).not.toMatch(/\d{15}/);
});
