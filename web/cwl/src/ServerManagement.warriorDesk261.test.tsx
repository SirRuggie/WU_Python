// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServerManagement from "./ServerManagement";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  transport.mockReset();
  transport.mockImplementation(async (path: string) => {
    if (path === "/manage")
      return {
        sections: [
          {
            id: "ticket_settings",
            label: "Ticket settings",
            description: "Channels and roles",
            group: "Recruitment",
            allowed: true,
            endpoint: "/manage/ticket-settings",
          },
        ],
      };
    if (path === "/manage/ticket-settings/desk")
      return {
        id: "ticket_settings",
        label: "Ticket settings",
        group: "Recruitment",
        revision: "fixture",
        fields: [],
        desk_readiness: { ready: true, live: false, missing: [] },
      };
    if (path === "/manage/ticket-settings")
      return {
        id: "ticket_settings",
        revision: "fixture",
        fields: [],
        documents: [
          {
            id: "desk",
            label: "Warrior Desk",
            endpoint: "/manage/ticket-settings/desk",
          },
          {
            id: "timers",
            label: "Ticket wait times",
            endpoint: "/manage/ticket-settings/timers",
          },
        ],
      };
    throw new Error(`Unlisted fixture ${path}`);
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("opens Warrior Desk from the channel group without an intermediate or self-link card", async () => {
  await act(async () =>
    root.render(<ServerManagement area="applications-settings" />),
  );
  const direct = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.startsWith("Warrior Desk"),
  )!;
  expect(direct).toBeDefined();
  await act(async () => direct.click());
  expect(transport.mock.calls.map(([path]) => path)).toEqual([
    "/manage",
    "/manage/ticket-settings/desk",
  ]);
  expect(host.querySelector("h1")?.textContent).toBe("Warrior Desk");
  expect(host.textContent).toContain("Ready to post");
  expect(host.querySelector(".manage-record-navigation")).toBeNull();
});
it("does not repeat Warrior Desk in the older ticket-settings document list", async () => {
  await act(async () =>
    root.render(<ServerManagement area="applications-settings" />),
  );
  const settings = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent?.startsWith("Ticket settings"),
  )!;
  await act(async () => settings.click());
  const nav = host.querySelector(".manage-record-navigation")!;
  expect(nav.textContent).toContain("Ticket wait times");
  expect(nav.textContent).not.toContain("Warrior Desk");
});

it("shows both named account roles and the shared staff channel without writes on read", async () => {
  const previous = transport.getMockImplementation()!;
  transport.mockImplementation(async (path: string, ...args: unknown[]) => {
    if (path === "/manage/ticket-settings/desk")
      return {
        id: "ticket_settings",
        label: "Ticket settings",
        group: "Recruitment",
        revision: "fixture",
        hint: "Staff threads use the Main staff channel.",
        fields: [
          {
            key: "main_staff_parent",
            label: "Staff thread channel",
            value: "21",
            type: "channel",
            readonly: true,
            options: [{ value: "21", label: "#recruit-staff", type: 0 }],
          },
          {
            key: "account_main_thread_recruiter_role",
            label: "Add account role (Main)",
            value: "104",
            type: "role",
            options: [{ value: "104", label: "Main account handlers" }],
          },
          {
            key: "account_fwa_thread_recruiter_role",
            label: "Add account role (FWA)",
            value: "105",
            type: "role",
            options: [{ value: "105", label: "FWA account handlers" }],
          },
        ],
      };
    return previous(path, ...args);
  });
  await act(async () =>
    root.render(<ServerManagement area="applications-settings" />),
  );
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((b) => b.textContent?.startsWith("Warrior Desk"))!
      .click(),
  );
  expect(host.textContent).toContain(
    "Staff threads use the Main staff channel.",
  );
  expect(host.textContent).toContain("Main account handlers");
  expect(host.textContent).toContain("FWA account handlers");
  expect(
    host.querySelector<HTMLButtonElement>("#manage-main-staff-parent")!
      .disabled,
  ).toBe(true);
  expect(
    host.querySelector("#manage-account-main-thread-recruiter-role"),
  ).not.toBeNull();
  expect(
    host.querySelector("#manage-account-fwa-thread-recruiter-role"),
  ).not.toBeNull();
  expect(
    transport.mock.calls.every(([, method]) => !method || method === "GET"),
  ).toBe(true);
});
