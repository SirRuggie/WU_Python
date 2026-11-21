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
