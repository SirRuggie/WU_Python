import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const hook = vi.hoisted(() => ({
  states: [] as unknown[],
  refs: [] as { current: number }[],
  stateIndex: 0,
  refIndex: 0,
  cleanup: undefined as (() => void) | undefined,
}));
const transport = vi.hoisted(() => vi.fn());

vi.mock("react", async (original) => {
  const actual = await original<typeof import("react")>();
  return {
    ...actual,
    useState: (initial: unknown) => {
      const index = hook.stateIndex++;
      if (!(index in hook.states))
        hook.states[index] =
          typeof initial === "function"
            ? (initial as () => unknown)()
            : initial;
      return [
        hook.states[index],
        (next: unknown) => {
          hook.states[index] =
            typeof next === "function"
              ? (next as (value: unknown) => unknown)(hook.states[index])
              : next;
        },
      ];
    },
    useRef: (initial: number) => {
      const index = hook.refIndex++;
      hook.refs[index] ||= { current: initial };
      return hook.refs[index];
    },
    useEffect: (effect: () => void | (() => void)) => {
      hook.cleanup?.();
      hook.cleanup = effect() || undefined;
    },
  };
});
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));

// Keep this flat-hook harness focused on the history request lifecycle. Shared
// identity rendering and URL/permission states have their own real React tests.
vi.mock("./DiscordIdentity", async () => {
  const { createElement } =
    await vi.importActual<typeof import("react")>("react");
  const actual =
    await vi.importActual<typeof import("./DiscordIdentity")>(
      "./DiscordIdentity",
    );
  return {
    ...actual,
    default: ({
      resolvedMember,
      displayName,
    }: {
      resolvedMember?: {
        display_name?: string;
        username?: string;
        avatar_url?: string;
      } | null;
      displayName?: string;
    }) =>
      createElement(
        "span",
        null,
        resolvedMember?.avatar_url &&
          createElement("img", { src: resolvedMember.avatar_url }),
        resolvedMember?.display_name ||
          displayName ||
          "Discord member unavailable",
        resolvedMember?.username,
      ),
  };
});
import { ApiError } from "./api";
import MemberActivityHistory from "./MemberActivityHistory";

const fixture = {
  id: "event-1",
  user_id: "123456789",
  event_type: "join" as const,
  display_name: "Example Member",
  username: "example",
  avatar_url: "/api/cwl/manage/member-events/event-1/avatar",
  occurred_at: "2026-10-26T12:00:00Z",
  delivery_status: "sent",
};
function render() {
  hook.stateIndex = 0;
  hook.refIndex = 0;
  return renderToStaticMarkup(createElement(MemberActivityHistory));
}
function reset() {
  hook.states = [];
  hook.refs = [];
  hook.stateIndex = 0;
  hook.refIndex = 0;
  hook.cleanup = undefined;
  transport.mockReset();
}

beforeEach(reset);
afterEach(() => {
  hook.cleanup?.();
  hook.cleanup = undefined;
});

it("keeps the compact history search and UTC filters visible while loading", () => {
  const html = render();
  expect(html).toContain(
    '<h2 id="member-activity-title">Activity history</h2>',
  );
  expect(html).toContain("Search name or Discord ID");
  expect(html).toContain("Activity");
  expect(html).toContain("<summary>Date range</summary>");
  expect(html).not.toContain('open=""');
  expect(html).toContain("From (UTC)");
  expect(html).toContain("To (UTC)");
  expect(html).toContain("Apply filters");
  expect(html).toContain("Loading member activity…");
  expect(html).not.toContain("No member activity has been recorded yet.");
});

it("sends bounded search, type, date, and cursor parameters to the API", async () => {
  hook.states[9] = {
    query: "Name 123",
    type: "leave",
    from: "2026-10-01",
    to: "2026-10-31",
  };
  transport.mockResolvedValue({ events: [], next_cursor: null });
  render();
  await Promise.resolve();
  const requestUrl = transport.mock.calls[0][0] as string;
  const params = new URLSearchParams(requestUrl.split("?")[1]);
  expect(params.get("limit")).toBe("50");
  expect(params.get("q")).toBe("Name 123");
  expect(params.get("type")).toBe("leave");
  expect(params.get("from")).toBe("2026-10-01");
  expect(params.get("to")).toBe("2026-10-31");
  expect(params.has("before")).toBe(false);
});

it("clears protected history when access is denied", async () => {
  hook.states[0] = [fixture];
  transport.mockRejectedValue(new ApiError("No access", 403));
  render();
  await Promise.resolve();
  await Promise.resolve();
  expect(hook.states[0]).toEqual([]);
  expect(hook.states[7]).toContain("Your staff access has changed.");
});

it("ignores a stale response after a newer filter read starts", async () => {
  let rejectOld!: (error: unknown) => void;
  let resolveNew!: (value: unknown) => void;
  transport
    .mockImplementationOnce(
      () =>
        new Promise((_resolve, reject) => {
          rejectOld = reject;
        }),
    )
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          resolveNew = resolve;
        }),
    );
  render();
  hook.states[9] = { query: "new name", type: "all", from: "", to: "" };
  render();
  resolveNew({
    events: [{ ...fixture, id: "new-event", display_name: "New Result" }],
    next_cursor: null,
  });
  await Promise.resolve();
  await Promise.resolve();
  rejectOld(new ApiError("Old request denied", 403));
  await Promise.resolve();
  await Promise.resolve();
  expect(hook.states[0]).toEqual([
    { ...fixture, id: "new-event", display_name: "New Result" },
  ]);
  expect(hook.states[7]).toBe("");
});

it("shows kick and ban reasons and moderators in the compact history card", () => {
  hook.states[0] = [
    {
      ...fixture,
      id: "kick-1",
      event_type: "kick",
      reason: "Spam <script>",
      moderator_id: "987654321",
      moderator_name: "<b>Moderator & Name</b>",
    },
    {
      ...fixture,
      id: "ban-1",
      event_type: "ban",
      reason: null,
      moderator_id: null,
    },
  ];
  const html = render();
  expect(html).toContain("Kicked");
  expect(html).toContain("Banned");
  expect(html).toContain("&lt;b&gt;Moderator &amp; Name&lt;/b&gt;");
  expect(html.replace(/<[^>]+>/g, "")).not.toContain("987654321");
  expect(html.replace(/<[^>]+>/g, "")).toContain(
    "an unknown moderator · “No reason given”",
  );
});

it("does not display archived raw-ID identity fallbacks", () => {
  hook.states[0] = [
    {
      ...fixture,
      display_name: fixture.user_id,
      username: fixture.user_id,
      event_type: "kick",
      moderator_id: "987654321",
      moderator_name: "987654321",
    },
  ];
  const visible = render().replace(/<[^>]+>/g, "");
  expect(visible).toContain("Discord member unavailable");
  expect(visible).toContain("Moderator: Unknown moderator");
  expect(visible).not.toContain(fixture.user_id);
  expect(visible).not.toContain("987654321");
});

it("labels timeout and profile rows and falls back for unknown types", () => {
  hook.states[0] = [
    {
      ...fixture,
      id: "t1",
      event_type: "timeout_add",
      reason: "Spam",
      moderator_id: "987654321",
      moderator_name: "Mod",
    },
    { ...fixture, id: "t2", event_type: "timeout_remove" },
    { ...fixture, id: "t3", event_type: "member_update" },
    { ...fixture, id: "t4", event_type: "future_kind" },
  ];
  const html = render();
  expect(html).toContain("Timed out");
  expect(html).toContain("Timeout removed");
  expect(html).toContain("Profile changed");
  expect(html).toContain("Activity</span>");
  expect(html).toContain("“Spam”");
  expect(html).toContain('<option value="timeout_add">Timeouts</option>');
  expect(html).toContain(
    '<option value="timeout_remove">Timeout removals</option>',
  );
  expect(html).toContain(
    '<option value="member_update">Profile changes</option>',
  );
});

it("labels the new history kinds, filters them and links to the member", () => {
  hook.states[0] = [
    {
      ...fixture,
      id: "u1",
      event_type: "unban",
      reason: "Appeal",
      moderator_id: "987654321",
      moderator_name: "Mod",
    },
    { ...fixture, id: "u2", event_type: "roles_added" },
    { ...fixture, id: "u3", event_type: "roles_removed" },
    { ...fixture, id: "u4", event_type: "invite_use" },
  ];
  const html = render();
  expect(html).toContain("Unbanned");
  expect(html).toContain("Roles added</span>");
  expect(html).toContain("Roles removed</span>");
  expect(html).toContain("Invite used");
  expect(html).toContain("“Appeal”");
  for (const value of ["unban", "roles_added", "roles_removed", "invite_use"])
    expect(html).toContain(`<option value="${value}">`);
});

it("keeps the unknown-type fallback", () => {
  hook.states[0] = [{ ...fixture, id: "x", event_type: "something_new" }];
  expect(render()).toContain("Activity</span>");
});

it("offers a View member action on every row without showing the raw id", () => {
  hook.states[0] = [fixture];
  const html = renderToStaticMarkup(
    createElement(MemberActivityHistory, { onViewMember: () => undefined }),
  );
  expect(html).toContain("View member");
  expect(html.replace(/<[^>]+>/g, "")).not.toContain(fixture.user_id);
});
