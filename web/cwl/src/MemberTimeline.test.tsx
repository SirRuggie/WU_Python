// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "./api";
import MemberTimeline from "./MemberTimeline";
import ModerationWorkspace from "./ModerationWorkspace";

const transport = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({
  ...(await original<typeof import("./api")>()),
  api: transport,
}));
vi.mock("./ModerationSettings", () => ({ default: () => <p>Settings</p> }));

const USER = "123456789012345678";
const member = {
  user_id: USER,
  display_name: "Example Member",
  username: "example",
  avatar_url: "/api/cwl/manage/member-events/e1/avatar",
};
const event = (id: string, type: string) => ({
  id,
  user_id: USER,
  event_type: type,
  display_name: "Example Member",
  username: "example",
  avatar_url: "/api/cwl/manage/member-events/e1/avatar",
  occurred_at: "2026-11-01T12:00:00Z",
});
let root: Root, host: HTMLDivElement;
const settle = async () => {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
};
const button = (label: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent?.trim() === label,
  );
const mountTimeline = async (onBack = vi.fn()) => {
  await act(async () =>
    root.render(<MemberTimeline userId={USER} onBack={onBack} />),
  );
  await settle();
  return onBack;
};

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  transport.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows the member header and events newest first without the raw id", async () => {
  transport.mockResolvedValue({
    member,
    events: [event("e2", "leave"), event("e1", "join")],
    next_before: null,
  });
  await mountTimeline();
  expect(transport).toHaveBeenCalledWith(
    `/manage/member-events/members/${USER}?limit=50`,
  );
  expect(host.querySelector(".member-timeline-member")?.textContent).toContain(
    "Example Member",
  );
  expect(host.querySelector(".member-timeline-member")?.textContent).toContain(
    "@example",
  );
  expect(
    [...host.querySelectorAll(".member-activity-kind")].map(
      (item) => item.textContent,
    ),
  ).toEqual(["🚪Left", "👋Joined"]);
  expect(
    host.querySelector('img[src="/api/cwl/manage/member-events/e1/avatar"]'),
  ).not.toBeNull();
  expect(host.textContent).not.toContain(USER);
  expect(button("Load more")).toBeUndefined();
  expect(button("View member")).toBeUndefined();
});

it("loads more with next_before and appends the rows", async () => {
  transport
    .mockResolvedValueOnce({
      member,
      events: [event("e2", "leave")],
      next_before: "cursor-1",
    })
    .mockResolvedValueOnce({
      member,
      events: [event("e1", "join")],
      next_before: null,
    });
  await mountTimeline();
  await act(async () => button("Load more")!.click());
  await settle();
  const url = transport.mock.calls[1][0] as string;
  expect(new URLSearchParams(url.split("?")[1]).get("before")).toBe("cursor-1");
  expect(host.querySelectorAll(".member-activity-row")).toHaveLength(2);
  expect(button("Load more")).toBeUndefined();
});

it("shows the loading state before the read finishes", async () => {
  transport.mockReturnValue(new Promise(() => undefined));
  await mountTimeline();
  expect(host.textContent).toContain("Loading member history…");
});

it("shows a quiet empty state for a 404", async () => {
  transport.mockRejectedValue(new ApiError("Not found", 404));
  await mountTimeline();
  expect(host.textContent).toContain("No history for this member.");
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.textContent).not.toContain(USER);
});

it("shows an error with a retry that reads again", async () => {
  transport.mockRejectedValueOnce(new Error("Server unavailable"));
  await mountTimeline();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(
    "Server unavailable",
  );
  transport.mockResolvedValueOnce({
    member,
    events: [event("e1", "join")],
    next_before: null,
  });
  await act(async () => button("Try again")!.click());
  await settle();
  expect(host.querySelector('[role="alert"]')).toBeNull();
  expect(host.querySelectorAll(".member-activity-row")).toHaveLength(1);
});

it("calls back from the header button", async () => {
  transport.mockResolvedValue({
    member,
    events: [event("e1", "join")],
    next_before: null,
  });
  const onBack = await mountTimeline();
  await act(async () => button("Activity history")!.click());
  expect(onBack).toHaveBeenCalledTimes(1);
});

it("opens the timeline from a history row and returns to history", async () => {
  transport.mockImplementation(async (path: string) =>
    path.startsWith("/manage/member-events/members/")
      ? { member, events: [event("e1", "join")], next_before: null }
      : { events: [event("e1", "join")], next_cursor: null },
  );
  const opened: string[] = [];
  const Harness = ({ id }: { id: string }) => (
    <ModerationWorkspace
      memberId={id}
      onMemberRoute={(value) => opened.push(value)}
    />
  );
  await act(async () => root.render(<Harness id="" />));
  await settle();
  await act(async () => button("View member")!.click());
  expect(opened).toEqual([USER]);

  await act(async () => root.render(<Harness id={USER} />));
  await settle();
  expect(host.querySelector(".member-timeline")).not.toBeNull();
  expect(
    host.querySelector("#member-activity-title")?.closest("[hidden]"),
  ).not.toBeNull();
  await act(async () => button("Activity history")!.click());
  expect(opened.at(-1)).toBe("");
});

it("deep link renders the timeline directly", async () => {
  transport.mockResolvedValue({
    member,
    events: [event("e1", "join")],
    next_before: null,
  });
  await act(async () => root.render(<ModerationWorkspace memberId={USER} />));
  await settle();
  expect(host.querySelector(".member-timeline")).not.toBeNull();
  expect(
    transport.mock.calls.some(([path]) =>
      String(path).startsWith("/manage/member-events?"),
    ),
  ).toBe(false);
});
