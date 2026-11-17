// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  afterEach,
  beforeEach,
  expect,
  it,
  vi,
  type MockInstance,
  type Mock,
} from "vitest";
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()),
  api: vi.fn(),
}));
import { api, ApiError } from "../api";
import MemberPersonPanel from "./MemberPersonPanel";
import type { DirectoryMember } from "./model";
import type { MembersDirectory } from "./useMembersDirectory";
import { membersText as t } from "./strings";
const uid = "123456789012345678",
  statusUrl = "/manage/requests/fixture-profile-240";
const member: DirectoryMember = {
  discord_id: uid,
  name: "Fixture Ada",
  nickname: "Ada | GMT+5:30 🇮🇳",
  discord_profile: { id: uid, display_name: "Fixture Ada" },
  role_ids: [],
  bot: false,
  status: "Saved",
  skip_reason: null,
  parsed: null,
  profile: {
    zone_id: "gmt+5:30",
    gmt_label: "GMT+5:30",
    utc_offset_minutes: 330,
    country: "IN",
    flag: "🇮🇳",
    name_source_tag: null,
    source: "staff",
    revision: 3,
  },
};
const directory: MembersDirectory = {
  members: [member],
  roles: [],
  manageable_roles: [],
  permission: "member_roles",
  countries: [{ code: "IN", label: "India", flag: "🇮🇳" }],
  zones: [{ id: "gmt+5:30", label: "GMT+5:30" }],
};
let host: HTMLDivElement, root: Root, mounted: boolean;
let onChanged: Mock<() => void>, onDenied: Mock<() => void>;
let poll: Mock<(path: string) => Promise<unknown>>,
  queue: Mock<() => Promise<unknown>>,
  interval: MockInstance;
let visibility: MockInstance<() => DocumentVisibilityState>;
function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => {
    resolve = yes;
  });
  return { promise, resolve };
}
beforeEach(() => {
  vi.useFakeTimers();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  visibility = vi
    .spyOn(document, "visibilityState", "get")
    .mockReturnValue("visible");
  interval = vi.spyOn(window, "setInterval");
  history.replaceState(null, "", "/server/members");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mounted = true;
  onChanged = vi.fn<() => void>();
  onDenied = vi.fn<() => void>();
  poll = vi
    .fn<(path: string) => Promise<unknown>>()
    .mockResolvedValue({ status: "pending", message: "Still saving" });
  queue = vi.fn<() => Promise<unknown>>().mockResolvedValue({
    request_id: "fixture-profile-240",
    status_url: statusUrl,
    status: "pending",
    message: "Queued",
  });
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (path.endsWith("/choices"))
      return { accounts: [], suggested: null, complete: true };
    if (path === "/manage/member-timezones/save" && method === "POST")
      return queue();
    return poll(path);
  });
});
afterEach(async () => {
  if (mounted) await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
async function render(current = member) {
  await act(async () =>
    root.render(
      <MemberPersonPanel
        member={current}
        data={directory}
        busy={false}
        navigationBusy={false}
        roleError=""
        onClose={() => {}}
        onDirty={() => {}}
        onDenied={onDenied}
        onChanged={onChanged}
        onRole={() => {}}
        onFix={() => {}}
      />,
    ),
  );
}
const button = (text: string) =>
  [...document.body.querySelectorAll("button")].find(
    (row) => row.textContent === text,
  )!;
async function click(text: string) {
  await act(async () => button(text).click());
}
async function save() {
  await render();
  await click(t.editTimeZone);
  await click("Save profile");
}
async function tick(ms = 2000) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}
function polls() {
  return vi
    .mocked(api)
    .mock.calls.filter(
      (call) =>
        call[0] !== "/manage/member-timezones/save" &&
        !call[0]?.endsWith("/choices"),
    );
}
function assertOriginalPaths() {
  expect(polls().every((call) => call[0] === statusUrl)).toBe(true);
  expect(
    vi
      .mocked(api)
      .mock.calls.some((call) => String(call[0]).includes("undefined")),
  ).toBe(false);
}
it("keeps queue identity across pending/running/done status-only replies with one interval", async () => {
  poll
    .mockResolvedValueOnce({ status: "pending", message: "Still saving" })
    .mockResolvedValueOnce({ status: "running", message: "Saving" })
    .mockResolvedValueOnce({
      status: "done",
      message: "Saved fixture profile",
    });
  await save();
  expect(document.querySelector(".mt-editor")).not.toBeNull();
  expect(polls()).toHaveLength(1);
  await tick(1999);
  expect(polls()).toHaveLength(1);
  await tick(1);
  expect(polls()).toHaveLength(2);
  expect(document.querySelector(".mt-editor")).not.toBeNull();
  await tick();
  expect(document.querySelector(".mt-editor")).toBeNull();
  expect(document.body.textContent).toContain("Saved fixture profile");
  expect(document.querySelector('[role="alert"]')).toBeNull();
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(interval.mock.calls.filter((call) => call[1] === 2000)).toHaveLength(
    1,
  );
  await tick(10000);
  expect(polls()).toHaveLength(3);
  assertOriginalPaths();
});
it.each(["failed", "uncertain"])(
  "shows server%s and stops polling",
  async (status) => {
    poll.mockResolvedValue({ status, message: "Fixture server explanation" });
    await save();
    await tick(10000);
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      "Fixture server explanation",
    );
    expect(document.querySelector(".mt-editor")).not.toBeNull();
    expect(polls()).toHaveLength(1);
    expect(onChanged).not.toHaveBeenCalled();
    assertOriginalPaths();
  },
);
it("keeps real-path404 uncertain without claiming completion", async () => {
  poll.mockRejectedValue(new ApiError("Real fixture status404", 404));
  await save();
  await tick(6000);
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(
    "Real fixture status404",
  );
  expect(polls()).toHaveLength(1);
  expect(onChanged).not.toHaveBeenCalled();
  assertOriginalPaths();
});
it.each([401, 403])(
  "preserves denied handling for%d and clears its timer",
  async (status) => {
    poll.mockRejectedValue(new ApiError("Denied", status));
    await save();
    await tick(6000);
    expect(onDenied).toHaveBeenCalledTimes(1);
    expect(onChanged).not.toHaveBeenCalled();
    expect(polls()).toHaveLength(1);
    assertOriginalPaths();
  },
);
it("never requests a missing statusURL and uses existing uncertainty copy", async () => {
  queue.mockResolvedValue({
    request_id: "fixture-profile-240",
    status: "pending",
    message: "Queued",
  });
  await save();
  await tick(6000);
  expect(polls()).toHaveLength(0);
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(
    t.roleUncertain,
  );
  expect(onChanged).not.toHaveBeenCalled();
});
it("pauses while hidden with the same cadence and URL", async () => {
  await save();
  visibility.mockReturnValue("hidden");
  await tick(6000);
  expect(polls()).toHaveLength(1);
  visibility.mockReturnValue("visible");
  await tick();
  expect(polls()).toHaveLength(2);
  assertOriginalPaths();
});
it("never overlaps a slow poll or restarts when it becomes running", async () => {
  const slow = deferred<{ status: string; message: string }>();
  poll.mockReturnValueOnce(slow.promise);
  await save();
  await tick(5000);
  expect(polls()).toHaveLength(1);
  await act(async () =>
    slow.resolve({ status: "running", message: "Still working" }),
  );
  expect(polls()).toHaveLength(1);
  await tick(999);
  expect(polls()).toHaveLength(1);
  await tick(1);
  expect(polls()).toHaveLength(2);
  expect(interval.mock.calls.filter((call) => call[1] === 2000)).toHaveLength(
    1,
  );
});
it.each(["done", "failed"])(
  "ignores stale%s after member change and preserves a newer queue",
  async (status) => {
    const old = deferred<{ status: string; message: string }>();
    poll.mockReturnValueOnce(old.promise);
    await save();
    const signal = polls()[0][3]?.signal;
    await render({
      ...member,
      discord_id: "223456789012345678",
      name: "Second fixture",
    });
    expect(signal?.aborted).toBe(true);
    await click(t.editTimeZone);
    queue.mockResolvedValue({
      request_id: "new-queue",
      status_url: "/manage/requests/new-queue",
      status: "pending",
      message: "New queue",
    });
    poll.mockResolvedValue({
      status: "pending",
      message: "New member pending",
    });
    await click("Save profile");
    await act(async () =>
      old.resolve({ status, message: "Old member result" }),
    );
    expect(document.body.textContent).not.toContain("Old member result");
    expect(document.querySelector(".mt-editor")).not.toBeNull();
    expect(onChanged).not.toHaveBeenCalled();
    await tick();
    expect(polls().at(-1)?.[0]).toBe("/manage/requests/new-queue");
  },
);
it("aborts on close/unmount and rejects a late result", async () => {
  const late = deferred<{ status: string; message: string }>();
  poll.mockReturnValueOnce(late.promise);
  await save();
  const signal = polls()[0][3]?.signal;
  await act(async () => root.unmount());
  mounted = false;
  expect(signal?.aborted).toBe(true);
  await act(async () =>
    late.resolve({ status: "done", message: "Old result" }),
  );
  await tick(6000);
  expect(polls()).toHaveLength(1);
  expect(onChanged).not.toHaveBeenCalled();
});
it("does not poll a submission resolved after the editor unmounts", async () => {
  const submit = deferred<object>();
  queue.mockReturnValue(submit.promise);
  await save();
  expect(queue).toHaveBeenCalledTimes(1);
  await act(async () => root.unmount());
  mounted = false;
  await act(async () =>
    submit.resolve({
      request_id: "old-queue",
      status_url: statusUrl,
      status: "pending",
      message: "Queued",
    }),
  );
  await tick(6000);
  expect(polls()).toHaveLength(0);
  expect(onChanged).not.toHaveBeenCalled();
});
it("a second Save tap while queued does not submit another mutation", async () => {
  await save();
  await click("Save profile");
  expect(queue).toHaveBeenCalledTimes(1);
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(1);
});

it("closes once on same-identity done replay after an accepted save response was lost", async () => {
  queue
    .mockRejectedValueOnce(new Error("Fixture queue response lost"))
    .mockResolvedValueOnce({
      request_id: "fixture-profile-240",
      status_url: statusUrl,
      status: "done",
      message: "Completed replay",
    });
  await save();
  expect(document.querySelector('[role="alert"]')?.textContent).toContain(
    "Fixture queue response lost",
  );
  expect(document.querySelector(".mt-editor")).not.toBeNull();
  expect(onChanged).not.toHaveBeenCalled();
  await click("Save profile");
  const posts = vi.mocked(api).mock.calls.filter((call) => call[1] === "POST");
  expect(posts).toHaveLength(2);
  expect(posts[1][2]).toEqual(posts[0][2]);
  expect(document.querySelector(".mt-editor")).toBeNull();
  expect(document.body.textContent).toContain("Completed replay");
  expect(document.querySelector('[role="alert"]')).toBeNull();
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(polls()).toHaveLength(0);
  expect(interval.mock.calls.filter((call) => call[1] === 2000)).toHaveLength(
    0,
  );
  await tick(10000);
  expect(onChanged).toHaveBeenCalledTimes(1);
  expect(polls()).toHaveLength(0);
});
it.each(["failed", "uncertain"])(
  "keeps an immediate queue%s explanation and permits explicit recovery",
  async (status) => {
    queue.mockResolvedValue({
      request_id: "fixture-profile-240",
      status_url: statusUrl,
      status,
      message: "Immediate fixture terminal explanation",
    });
    await save();
    expect(document.querySelector(".mt-editor")).not.toBeNull();
    expect(document.querySelector('[role="alert"]')?.textContent).toContain(
      "Immediate fixture terminal explanation",
    );
    expect(button("Save profile").disabled).toBe(false);
    await tick(6000);
    expect(onChanged).not.toHaveBeenCalled();
    expect(polls()).toHaveLength(0);
  },
);
