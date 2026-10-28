// @vitest-environment happy-dom
import * as manageBridge from "./manageBridge";
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import ManageBridgeWorkspace from "./ManageBridgeWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
import type { ManageBridge } from "./manageBridge";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DiscordMessagePreview", () => ({
  default: () => <div>Discord preview</div>,
}));
vi.mock("./ChannelCombobox", () => ({
  default: ({
    label,
    value,
    onChange,
    disabled,
  }: {
    label: string;
    value: string;
    onChange: (v: string) => void;
    disabled: boolean;
  }) => (
    <input
      aria-label={label}
      value={value}
      disabled={disabled}
      onChange={(e) => onChange(e.target.value)}
    />
  ),
}));
let host: HTMLDivElement,
  root: ReturnType<typeof createRoot>,
  bridge: ManageBridge;
const dirty = vi.fn();
const channels = [
  { id: "111111111111111111", name: "main-cwl" },
  { id: "222222222222222222", name: "lazy-cwl" },
];
const button = (text: string, scope: ParentNode = document) =>
  [...scope.querySelectorAll("button")].find((b) => b.textContent === text)!;
async function click(text: string, scope: ParentNode = document) {
  await act(async () => button(text, scope).click());
}
async function mount(owner = true) {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner, permissions: [] }}>
        <ManageBridgeWorkspace
          seasonId="1"
          seasonLabel="November 2026"
          publicationVersion={2}
          onDirty={dirty}
        />
      </DashboardPermissions.Provider>,
    ),
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  api.mockReset();
  dirty.mockReset();
  const pool = {
    title: "CWL roster",
    body: "Your roster is ready",
    media_url: null,
    buttons: [],
    role_ids: ["333333333333333333"],
    enabled: true,
    delivery: null,
    roster_url: "https://example.test/assignments?season=1",
  };
  bridge = {
    cycle: "2026-11",
    generation: "g1",
    worker_ready: true,
    published_version: 2,
    pools: {
      main: { ...pool, channel_id: channels[0].id },
      lazy: { ...pool, channel_id: channels[1].id },
    },
  };
  api.mockImplementation(
    async (path: string, method?: string, body?: Record<string, unknown>) => {
      if (method === "POST" && path.endsWith("/bind")) {
        bridge = { ...bridge, cycle: body!.cycle as string };
        return {};
      }
      if (method === "PATCH") {
        const pool = path.includes("/main") ? "main" : "lazy";
        bridge = {
          ...bridge,
          generation: "g2",
          pools: {
            ...bridge.pools,
            [pool]: { ...bridge.pools[pool], ...body },
          },
        };
        return {};
      }
      if (method === "POST" && path.endsWith("/send"))
        return { delivery: { status: "pending" } };
      if (path.includes("manage-bridge")) return structuredClone(bridge);
      if (path.endsWith("roles"))
        return { roles: [{ id: "333333333333333333", name: "CWL players" }] };
      return { channels };
    },
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("loads the derived month only on tap, then confirms a linked change once", async () => {
  bridge.cycle = null;
  await mount();
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
  await click("Load November 2026");
  expect(api.mock.calls.filter((c) => c[1] === "POST")).toEqual([
    ["/seasons/1/manage-bridge/bind", "POST", { cycle: "2026-11" }],
  ]);
  await click("Change");
  const input = host.querySelector<HTMLInputElement>('input[type="month"]')!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(input, "2026-12");
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await click("Change month");
  expect(document.querySelectorAll(".confirm-dialog")).toHaveLength(1);
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "from 2026-11 to 2026-12",
  );
  await click("Cancel");
  expect(api.mock.calls.filter((c) => c[1] === "POST")).toHaveLength(1);
});
it("shows both cards without tabs, opens Preview and an unsaved prefilled Edit", async () => {
  vi.spyOn(manageBridge, "isSecureOrigin").mockReturnValue(true);
  bridge.pools.main.roster_url = "";
  await mount();
  expect(host.querySelectorAll(".announcement-pool-card")).toHaveLength(2);
  expect(host.querySelector('[role="tablist"]')).toBeNull();
  await click("Preview");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Discord preview",
  );
  await click("Close ×");
  await click("Edit");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "/assignments?season=1",
  );
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Unsaved changes",
  );
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
});
it("keeps custom links and saving uses the current generation without sending", async () => {
  bridge.pools.main.roster_url = "https://custom.test/roster";
  await mount();
  await click("Edit");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "https://custom.test/roster",
  );
  expect(button("Save message").disabled).toBe(true);
  const textarea = document.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLTextAreaElement.prototype,
      "value",
    )!.set!.call(textarea, "Changed message");
    textarea.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Save message");
  expect(api.mock.calls.find((c) => c[1] === "PATCH")?.[2]).toMatchObject({
    generation: "g1",
    body: "Changed message",
    roster_url: "https://custom.test/roster",
  });
  expect(api.mock.calls.some((c) => c[0].endsWith("/send"))).toBe(false);
});
it("reviews only ready pools and reports partial results; duplicate confirm cannot queue twice", async () => {
  await mount();
  expect(button("Send")).toBeUndefined();
  await click("Review and send");
  expect(
    document.querySelectorAll(".announcement-send-review section"),
  ).toHaveLength(2);
  const original = api.getMockImplementation()!;
  api.mockImplementation(async (...args: unknown[]) => {
    if (String(args[0]).endsWith("/lazy/send"))
      throw new Error("Changed by another staff member");
    return original(...args);
  });
  const confirm = button("Queue both announcements");
  await act(async () => {
    confirm.click();
    confirm.click();
  });
  expect(
    api.mock.calls.filter((c) => String(c[0]).endsWith("/send")),
  ).toHaveLength(2);
  expect(host.textContent).toContain("Main CWL queued.");
  expect(host.textContent).toContain("Changed by another staff member");
});
it("offers Retry only for the ready failed pool and never for sent or uncertain", async () => {
  bridge.pools.main.delivery = { status: "sent" };
  bridge.pools.lazy.delivery = { status: "failed" };
  await mount();
  expect(host.querySelectorAll(".announcement-pool-card button")).toHaveLength(
    5,
  );
  await click("Review and send");
  expect(
    document.querySelectorAll(".announcement-send-review section"),
  ).toHaveLength(1);
  await click("Cancel");
  expect(button("Retry")).toBeDefined();
});
it("without cwl_send no editing, binding, or send is enabled", async () => {
  await mount(false);
  expect(button("Edit")).toBeUndefined();
  expect(button("Review and send").disabled).toBe(true);
  expect(button("Change").disabled).toBe(true);
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
});
it("refresh with edits is one Cancel-first confirmation and Cancel preserves edits", async () => {
  vi.spyOn(manageBridge, "isSecureOrigin").mockReturnValue(true);
  bridge.pools.main.roster_url = "";
  await mount();
  await click("Edit");
  const close =
    document.querySelector<HTMLButtonElement>(".action-panel-close") ||
    [...document.querySelectorAll<HTMLButtonElement>("dialog button")].find(
      (b) =>
        b.getAttribute("aria-label")?.includes("Close") ||
        b.textContent === "Close",
    )!;
  await act(async () => close.click());
  await click("Refresh status");
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Discard unsaved announcement edits and reload?",
  );
  await click("Cancel");
  expect(dirty).toHaveBeenLastCalledWith(true);
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
  expect(
    [...host.querySelectorAll("button")].filter(
      (b) => b.textContent === "Refresh status",
    ),
  ).toHaveLength(1);
});
it("test send requires the no-pings confirmation and cannot queue a real announcement", async () => {
  await mount();
  await click("Edit");
  const field = document.querySelector<HTMLInputElement>(
    'input[aria-label="Test channel"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, channels[0].id);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Send test");
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Send a Main test to #main-cwl? No roles are pinged and the real announcement stays unsent.",
  );
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
  await click("Cancel");
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
  await click("Send test");
  await click("Confirm");
  expect(api.mock.calls.filter((c) => c[1] === "POST")).toHaveLength(1);
  expect(api.mock.calls.find((c) => c[1] === "POST")?.[0]).toBe(
    "/seasons/1/manage-bridge/main/test",
  );
});
it("bot unavailable prevents all sends, and loading explains the wait without hiding the header", async () => {
  bridge.worker_ready = false;
  await mount();
  expect(host.textContent).toContain(
    "The bot can't send right now. Refresh status in a minute.",
  );
  expect(button("Review and send").disabled).toBe(true);
  expect(host.textContent).not.toContain("Sender ready");
});
it("HTTP origins leave an empty roster link untouched", async () => {
  expect(manageBridge.isSecureOrigin()).toBe(false);
  bridge.pools.main.roster_url = "";
  await mount();
  await click("Edit");
  expect(dirty).toHaveBeenLastCalledWith(false);
  expect(button("Save message").disabled).toBe(true);
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
});
it("a test-send guard closes the confirmation and explains why nothing was sent", async () => {
  await mount();
  await click("Edit");
  const field = document.querySelector<HTMLInputElement>(
    'input[aria-label="Test channel"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(field, channels[0].id);
    field.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await click("Send test");
  await mount(false);
  await click("Confirm");
  expect(document.querySelector(".confirm-dialog")).toBeNull();
  expect(host.textContent).toContain("Test not sent:");
  expect(api.mock.calls.some((c) => c[1])).toBe(false);
});
