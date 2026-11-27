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
  hint: "A saved channel hint.",
  warning: "Test window is open.",
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
            message: "Queued. Waiting to start.",
          };
    if (path === "/manage/requests/267")
      return outcome === "queued_done"
        ? {
            status: "done",
            message: "Warrior Desk panel posted and bound.",
            result: {
              message: "Warrior Desk panel posted and bound.",
              details: "Existing details retained.",
              url: "https://discord.com/channels/1/2/3",
            },
          }
        : { status: outcome, message: ERROR };
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
it("shows one direct-save success without an error", async () => {
  outcome = "done";
  await save();
  expect(host.querySelector(".load-error")).toBeNull();
  expect(host.querySelectorAll(".manage-result")).toHaveLength(1);
  expect(host.querySelector(".manage-result")?.textContent).toBe("Saved.");
  expect(
    [...host.querySelectorAll(".manage-notice")].some(
      (node) => node.textContent === "Saved.",
    ),
  ).toBe(false);
});

it("queued save shows the worker result once and keeps hints distinct from warnings", async () => {
  outcome = "queued_done";
  await save();
  const result = host.querySelector(".manage-result")!;
  expect(result.getAttribute("role")).toBe("status");
  expect(result.textContent).toContain("Warrior Desk panel posted and bound.");
  expect(result.textContent).toContain("Existing details retained.");
  expect(result.querySelector("a")?.href).toBe(
    "https://discord.com/channels/1/2/3",
  );
  expect(
    host.textContent?.split("Warrior Desk panel posted and bound."),
  ).toHaveLength(2);
  expect(host.querySelector(".manage-status")).toBeNull();
  expect(host.querySelector(".manage-hint")?.textContent).toBe(
    "A saved channel hint.",
  );
  expect(
    host.querySelector(".manage-hint svg")?.getAttribute("aria-hidden"),
  ).toBe("true");
  expect(host.querySelector(".manage-notice")?.textContent).toBe(
    "Test window is open.",
  );
  expect(
    host.querySelector(".manage-notice svg")?.getAttribute("aria-hidden"),
  ).toBe("true");
  expect(host.querySelector(".manage-result h3")).toBeNull();
  const change = pickerByLabel(host, "Warrior Desk channel");
  await pickOption(change, "#staff");
  let resolve!: (value: unknown) => void;
  transport.mockImplementationOnce(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const button = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (node) => node.textContent === "Save changes",
  )!;
  await act(async () => button.click());
  expect(host.querySelector(".manage-result")).toBeNull();
  await act(async () =>
    resolve({
      ...doc,
      fields: doc.fields.map((field) => ({
        ...field,
        value: "222222222222222222",
      })),
    }),
  );
});
