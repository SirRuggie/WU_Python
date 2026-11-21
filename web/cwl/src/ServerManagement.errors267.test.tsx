// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ServerManagement from "./ServerManagement";
import { pickerByLabel, pickOption } from "./searchPickerTestUtils";
const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./useCompactPreview", () => ({ default: () => false }));
const ERROR =
  "Ticket settings check failed: handler role Recruitment Team is missing View Channel in #warrior-desk. Nothing was saved or posted.";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>, outcome: string;
const doc = {
  id: "ticket_settings",
  label: "Ticket settings",
  description: "Channels and roles",
  group: "Recruitment",
  allowed: true,
  endpoint: "/manage/ticket-settings",
  revision: "r267",
  fields: [
    {
      key: "desk_channel_id",
      label: "Warrior Desk channel",
      type: "channel",
      value: "111111111111111111",
      options: [
        { value: "111111111111111111", label: "#warrior-desk", type: 0 },
        { value: "222222222222222222", label: "#staff", type: 0 },
      ],
    },
  ],
};
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
  outcome = "failed";
  transport.mockReset();
  transport.mockImplementation(async (path: string, method?: string) => {
    if (path === "/manage") return { sections: [doc] };
    if (method === "PATCH")
      return outcome === "done"
        ? {
            ...doc,
            fields: doc.fields.map((field) => ({
              ...field,
              value: "222222222222222222",
            })),
          }
        : {
            status: "pending",
            status_url: "/manage/requests/267",
            message: "Queued. Waiting for the bot.",
          };
    if (path === "/manage/requests/267")
      return { status: outcome, message: ERROR };
    return doc;
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function save() {
  await act(async () =>
    root.render(<ServerManagement area="applications-settings" />),
  );
  const desk = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent?.startsWith("Warrior Desk"),
  )!;
  await act(async () => desk.click());
  await pickOption(pickerByLabel(host, "Warrior Desk channel"), "#staff");
  const save = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent === "Save changes",
  )!;
  await act(async () => save.click());
}
it.each(["failed", "uncertain"])(
  "shows one proper error and no duplicate olive notice for %s",
  async (status) => {
    outcome = status;
    await save();
    expect(host.querySelectorAll(".load-error")).toHaveLength(1);
    expect(host.querySelector(".load-error")?.textContent).toContain(ERROR);
    expect(
      [...host.querySelectorAll(".manage-notice")].some(
        (node) => node.textContent === ERROR,
      ),
    ).toBe(false);
    expect(host.querySelector(".load-error button")?.textContent).toBe(
      "Try again",
    );
    expect(transport.mock.calls.filter(([, method]) => method)).toHaveLength(1);
  },
);
it("retains the normal saved notice without an error", async () => {
  outcome = "done";
  await save();
  expect(host.querySelector(".load-error")).toBeNull();
  expect(
    [...host.querySelectorAll(".manage-notice")].some(
      (node) => node.textContent === "Saved.",
    ),
  ).toBe(true);
});
