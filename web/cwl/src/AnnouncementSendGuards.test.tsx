// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import ManageBridgeWorkspace from "./ManageBridgeWorkspace";
import { DashboardPermissions } from "./DashboardPermissions";
import type { ManageBridge } from "./manageBridge";
const { api, review } = vi.hoisted(() => ({
  api: vi.fn(),
  review: {
    current: null as null | { onConfirm: () => void; pools: { key: string }[] },
  },
}));
// Expose the workspace callback without the dialog's separate submitted-ref guard.
vi.mock("./AnnouncementSendReview", () => ({
  default: (props: NonNullable<typeof review.current>) => {
    review.current = props;
    return <div>Review open</div>;
  },
}));
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
  review.current = null;
  vi.useFakeTimers();
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
  vi.useRealTimers();
  vi.restoreAllMocks();
});

const sends = () =>
  api.mock.calls.filter((c) => String(c[0]).endsWith("/send"));
const reads = () =>
  api.mock.calls.filter((c) => c[0] === "/seasons/1/manage-bridge" && !c[1]);
it("workspace send ref rejects two simultaneous confirmations independently of the dialog", async () => {
  await mount();
  await click("Review and send");
  const confirm = review.current!.onConfirm;
  const original = api.getMockImplementation()!;
  let release!: () => void;
  const pending = new Promise<void>((resolve) => {
    release = resolve;
  });
  api.mockImplementation(async (...args: unknown[]) => {
    if (String(args[0]).endsWith("/send")) await pending;
    return original(...args);
  });
  await act(async () => {
    confirm();
    confirm();
  });
  expect(sends()).toHaveLength(1);
  await act(async () => release());
  expect(sends().map((c) => c[0])).toEqual([
    "/seasons/1/manage-bridge/main/send",
    "/seasons/1/manage-bridge/lazy/send",
  ]);
});
it("stale draft generation cannot offer or queue a ready pool after polling", async () => {
  bridge.pools.main.delivery = { status: "pending" };
  await mount();
  bridge.generation = "g2";
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(reads()).toHaveLength(2);
  expect(button("Review and send").disabled).toBe(true);
  expect(button("Send")).toBeUndefined();
  await click("Review and send");
  expect(review.current).toBeNull();
  expect(sends()).toHaveLength(0);
});
it("workspace rechecks ready pools when permission is lost after review opens", async () => {
  await mount();
  await click("Review and send");
  expect(review.current!.pools).toHaveLength(2);
  await mount(false);
  await act(async () => review.current!.onConfirm());
  expect(sends()).toHaveLength(0);
});
it("polling pauses for review and cannot replace the reviewed state", async () => {
  bridge.pools.main.delivery = { status: "pending" };
  await mount();
  await click("Review and send");
  expect(review.current!.pools.map((p) => p.key)).toEqual(["lazy"]);
  bridge.generation = "g2";
  bridge.pools.lazy.delivery = { status: "sent" };
  await act(async () => {
    await vi.advanceTimersByTimeAsync(15000);
  });
  expect(reads()).toHaveLength(1);
  expect(review.current!.pools.map((p) => p.key)).toEqual(["lazy"]);
  expect(sends()).toHaveLength(0);
});
