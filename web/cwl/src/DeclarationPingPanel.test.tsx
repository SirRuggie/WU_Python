// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mock.api,
}));
import { ApiError } from "./api";
import DeclarationPingPanel from "./DeclarationPingPanel";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const state = {
  revision: 1,
  channel: { id: "234567890123456789", name: "pings" },
  can_send: true,
  channels: [
    { id: "234567890123456789", name: "pings", type: 0, can_send: true },
  ],
  active: null,
  test_running: false,
  history: [],
  cooldown_until: 0,
  test_channel: { id: "345678901234567890", name: "test", revision: 1 },
};
const review = {
  token: "a".repeat(32),
  mode: "live",
  channel: state.channel,
  count: 26,
  unknown: 3,
  unlinked: 1,
  chunks: 1,
  groups: [
    {
      tag: "#PYY",
      name: "Fixture clan",
      accounts: Array(26).fill({ tag: "#PYY", name: "Player" }),
      users: ["123456789012345678"],
      unlinked: [{ tag: "#PYY", name: "Unlinked player" }],
    },
  ],
  previews: [
    [
      {
        type: "container",
        children: [{ type: "text", text: "Total missing: 26" }],
      },
    ],
  ],
};
const flush = () =>
  act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
function button(text: string) {
  return [...document.querySelectorAll("button")].find(
    (b) => b.textContent === text,
  )!;
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  Element.prototype.scrollIntoView = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mock.api
    .mockReset()
    .mockImplementation(async (path: string) =>
      path.endsWith("/preview")
        ? review
        : path.endsWith("/send")
          ? {
              receipt: {
                token: review.token,
                actor_id: "owner",
                state: "done",
                created_at: 1,
                count: 26,
                chunks: 1,
                posted: [{ chunk: 0, message_id: "456789012345678901" }],
                attempting: null,
                channel: state.channel,
              },
            }
          : state,
    );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
async function mount() {
  await act(async () =>
    root.render(<DeclarationPingPanel seasonId="1" pool="lazy" missing={26} />),
  );
  await flush();
}
it("fresh review is separate from explicit send and cancel sends nothing", async () => {
  await mount();
  expect(mock.api.mock.calls.every((c) => c[1] === "GET")).toBe(true);
  await act(async () => button("Ping 26 missing").click());
  await flush();
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Ping 26 players in #pings?",
  );
  expect(document.body.textContent).toContain("Unlinked player");
  expect(mock.api.mock.calls.some((c) => c[0].endsWith("/send"))).toBe(false);
  await act(async () => button("Cancel").click());
  expect(document.querySelector("dialog")).toBeNull();
  expect(mock.api.mock.calls.some((c) => c[0].endsWith("/send"))).toBe(false);
  await act(async () => button("Ping 26 missing").click());
  await flush();
  await act(async () => {
    button("Send pings").click();
    button("Send pings")?.click();
  });
  await flush();
  const calls = mock.api.mock.calls.filter((c) => c[0].endsWith("/send"));
  expect(calls).toHaveLength(1);
  expect(calls[0][2]).toEqual({
    token: review.token,
    confirm: true,
    send_again: false,
  });
});
it("read-only staff see state without send or channel controls", async () => {
  mock.api.mockResolvedValue({ ...state, can_send: false, channels: [] });
  await mount();
  expect(document.body.textContent).toContain("Read-only access");
  expect(host.querySelector("button")).toBeNull();
});
it("permission loss clears the review and protected state", async () => {
  await mount();
  await act(async () => button("Ping 26 missing").click());
  await flush();
  mock.api.mockRejectedValue(new ApiError("Permission removed", 403));
  await act(async () => button("Send pings").click());
  await flush();
  expect(document.querySelector("dialog")).toBeNull();
  expect(host.textContent).toContain("Permission removed");
  expect(button("Ping 26 missing")).toBeUndefined();
});
it("no-ping test uses its own review mode and confirmation", async () => {
  mock.api.mockImplementation(async (path: string) =>
    path.endsWith("/preview")
      ? {
          ...review,
          mode: "test",
          channel: { id: state.test_channel.id, name: "test" },
        }
      : state,
  );
  await mount();
  await act(async () => button("Send test").click());
  await flush();
  expect(
    mock.api.mock.calls.find((c) => c[0].endsWith("/preview"))?.[2],
  ).toEqual({ revision: 1, mode: "test" });
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Nobody will be pinged",
  );
  expect(mock.api.mock.calls.some((c) => c[0].endsWith("/send"))).toBe(false);
});
it("ignores an abandoned pool response", async () => {
  let resolve!: (value: unknown) => void;
  mock.api.mockImplementationOnce(() => new Promise((r) => (resolve = r)));
  await mount();
  await act(async () =>
    root.render(
      <DeclarationPingPanel key="main" seasonId="1" pool="main" missing={65} />,
    ),
  );
  await flush();
  await act(async () =>
    resolve({ ...state, channel: { id: "old", name: "old abandoned pool" } }),
  );
  await flush();
  expect(host.textContent).not.toContain("old abandoned pool");
  expect(button("Ping 65 missing")).toBeDefined();
});
