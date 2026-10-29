// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({ can: true, data: null as any }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => state.can,
}));
vi.mock("./SingleClanRosterTest", () => ({ default: () => null }));
vi.mock("./ChannelCombobox", () => ({
  default: ({ label, onChange }: any) => (
    <button onClick={() => onChange("123")}>{label}</button>
  ),
}));
vi.mock("./ActionPanel", () => ({
  default: ({ children, footer, onClose }: any) => (
    <div>
      {children}
      {footer}
      <button onClick={onClose}>Close test</button>
    </div>
  ),
}));
vi.mock("./ConfirmDialog", () => ({
  default: ({ text, onCancel, onConfirm, children }: any) => (
    <div role="dialog">
      {text}
      {children}
      <button onClick={onCancel}>Cancel</button>
      <button onClick={onConfirm}>Confirm</button>
    </div>
  ),
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<any>()),
  api: vi.fn(),
}));
import { api } from "./api";
import ClanRosterImages from "./ClanRosterImages";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  state.can = true;
  state.data = {
    published: { version: 1, published_at: "2026-10-28T12:00:00Z" },
    last_publication: null,
    posts: [],
    clans: [
      { tag: "#C2Y", name: "Main Clan", pool: "main", pages: 1, count: 15 },
    ],
  };
  vi.mocked(api).mockImplementation(async (path) =>
    path === "/roster-image-channels"
      ? {
          channels: [
            { pool: "main", channel_id: "123", channel_name: "rosters" },
          ],
        }
      : path === "/announcement-channels"
        ? { channels: [{ id: "123", name: "rosters" }] }
        : structuredClone(state.data),
  );
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.clearAllMocks();
});
const render = () =>
  act(async () => root.render(<ClanRosterImages seasonId="1" version={1} />));
const button = (name: string) =>
  [...host.querySelectorAll("button")].find((b) => b.textContent === name)!;
const writes = () => vi.mocked(api).mock.calls.filter((c) => c[1] === "POST");
it("opening and cancelling the run never sends; Confirm is guarded against double taps", async () => {
  await render();
  expect(writes()).toHaveLength(0);
  await act(async () => button("Post Main").click());
  expect(host.textContent).toContain("Post 1 clans to #rosters? No pings.");
  expect(writes()).toHaveLength(0);
  await act(async () => button("Cancel").click());
  expect(writes()).toHaveLength(0);
  await act(async () => button("Post Main").click());
  await act(async () => {
    button("Confirm").click();
    button("Confirm").click();
  });
  expect(writes()).toHaveLength(1);
});
it("view-only and hidden states expose no send controls", async () => {
  state.can = false;
  await render();
  expect(button("Post Main")).toBeUndefined();
  expect(writes()).toHaveLength(0);
  state.can = true;
  state.data.published = null;
  state.data.last_publication = {
    version: 1,
    published_at: "2026-10-28T12:00:00Z",
    withdrawn_at: "2026-10-28T13:00:00Z",
  };
  await act(async () =>
    root.render(<ClanRosterImages seasonId="2" version={null} />),
  );
  expect(host.textContent).toContain("Hidden from members");
  expect(button("Post Main")).toBeUndefined();
});
it("uncertain edits use explicit same-message confirmation", async () => {
  state.data.posts = [
    {
      clan_tag: "#C2Y",
      pool: "main",
      channel_id: "123",
      message_id: "456",
      status: "uncertain",
      posted_version: 1,
      target_version: 2,
      operation: "update",
    },
  ];
  state.data.published.version = 2;
  await render();
  await act(async () => button("Retry the edit with version 2").click());
  expect(host.textContent).toContain(
    "Retry the edit on the same message with version 2? This won't create a new message.",
  );
  expect(writes()).toHaveLength(0);
  await act(async () => button("Confirm").click());
  expect(writes()[0][0]).toContain("/update");
});

it("Test all asks for a test-only destination and confirmation; it only uses the test endpoint", async () => {
  state.data.clans.push({
    tag: "#L2Y",
    name: "Lazy Clan",
    pool: "lazy",
    pages: 1,
    count: 15,
  });
  await render();
  await act(async () => button("Test all…").click());
  await act(async () => button("Test channel").click());
  await act(async () => button("Review test").click());
  expect(host.textContent).toContain(
    "Post a TEST copy of every Main and Lazy clan to #rosters? No pings. Nothing is recorded as posted.",
  );
  expect(writes()).toHaveLength(0);
  await act(async () => button("Confirm").click());
  expect(writes()).toHaveLength(2);
  expect(
    writes().every(
      (c) => c[0].includes("/roster-images/") && c[0].endsWith("/test"),
    ),
  ).toBe(true);
  expect(vi.mocked(api).mock.calls.some((c) => c[1] === "PUT")).toBe(false);
});
it("permission loss while confirming cancels the send", async () => {
  await render();
  await act(async () => button("Post Main").click());
  state.can = false;
  await render();
  expect(button("Confirm")).toBeUndefined();
  expect(writes()).toHaveLength(0);
});

it.each(["post", "update", "drop"])(
  "uncertain %s recovery targets the new publication after republish",
  async (operation) => {
    state.data.posts = [
      {
        clan_tag: "#C2Y",
        pool: "main",
        channel_id: "123",
        message_id: operation === "post" ? null : "456",
        status: "uncertain",
        posted_version: 1,
        target_version: 1,
        operation,
      },
    ];
    await render();
    state.data.published.version = 2;
    await act(async () =>
      root.render(<ClanRosterImages seasonId="1" version={2} />),
    );
    expect(host.textContent).toContain("1 needs checking");
    await act(async () =>
      button(
        operation === "post"
          ? "Post again anyway · version 2"
          : "Retry the edit with version 2",
      ).click(),
    );
    expect(writes()).toHaveLength(0);
    expect(host.textContent).toContain(
      operation === "post"
        ? "This can create a duplicate message"
        : "same message with version 2",
    );
    await act(async () => button("Confirm").click());
    expect(writes()[0][2]).toMatchObject({ version: 2 });
    if (operation === "post")
      expect(writes()[0][2]).toHaveProperty("confirm_duplicate", true);
    else expect(writes()[0][2]).not.toHaveProperty("confirm_duplicate");
    if (operation !== "post") expect(writes()[0][0]).toContain("/update");
  },
);

it.each(["post", "update"])(
  "removed uncertain %s has a confirmed recovery",
  async (operation) => {
    state.data.posts = [
      {
        clan_tag: "#C2Y",
        clan_name: "Old Clan",
        pool: "main",
        channel_id: "123",
        message_id: operation === "post" ? null : "456",
        status: "uncertain",
        posted_version: 1,
        target_version: 1,
        operation,
      },
    ];
    state.data.clans = [];
    state.data.published.version = 2;
    await render();
    const label =
      operation === "post"
        ? "Mark as checked"
        : "Mark as no longer hosting · version 2";
    expect(button("Post again anyway · version 2")).toBeUndefined();
    if (operation === "post")
      expect(host.textContent).toContain(
        "Check Discord for Old Clan's post. It's no longer in the roster.",
      );
    await act(async () => button(label).click());
    expect(writes()).toHaveLength(0);
    expect(host.textContent).toContain(
      operation === "post"
        ? "won't change anything in Discord"
        : "Edit the existing message to say Old Clan is no longer hosting? This won't create a new message.",
    );
    await act(async () => button("Cancel").click());
    expect(writes()).toHaveLength(0);
    await act(async () => button(label).click());
    await act(async () => button("Confirm").click());
    expect(writes()).toHaveLength(1);
    expect(writes()[0][0]).toMatch(
      operation === "post" ? /\/dismiss$/ : /\/drop$/,
    );
    expect(writes()[0][2]).toMatchObject({ pool: "main", version: 2 });
    expect(writes()[0][2]).not.toHaveProperty("confirm_duplicate");
  },
);

it("ordinary Post does not assert duplicate consent", async () => {
  await render();
  await act(async () => button("Post Main").click());
  await act(async () => button("Confirm").click());
  expect(writes()[0][2]).not.toHaveProperty("confirm_duplicate");
});
