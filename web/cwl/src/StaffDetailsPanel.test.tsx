// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const spy = vi.hoisted(() => ({ props: null as any }));
vi.mock("./RosterPlayerDialog", () => ({
  default: (props: any) => {
    spy.props = props;
    return (
      <div>
        {props.error}
        {props.undo}
      </div>
    );
  },
}));
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
import StaffDetailsPanel from "./StaffDetailsPanel";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const changed = vi.fn();
const snapshot = (revision = 1, undo: unknown = null) => ({
  revision,
  accounts: [{ tag: "#PLAYER" }],
  clans: [],
  undo,
});
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
  changed.mockReset();
  vi.mocked(api).mockResolvedValue(snapshot());
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function render() {
  await act(async () =>
    root.render(
      <StaffDetailsPanel
        request={{ seasonId: "1", tag: "#PLAYER", onChanged: changed }}
        setRequest={vi.fn()}
      />,
    ),
  );
}
it("guards double submissions while saving, sends exact Change clan PATCH and revision, and Undo restores", async () => {
  await render();
  let finish!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (method === "PATCH")
      return (await new Promise<unknown>((done) => {
        finish = done;
      })) as never;
    if (method === "POST") return {} as never;
    return snapshot(path.endsWith("/roster") ? 2 : 1, {
      id: "receipt",
      label: "Edit account placement",
    }) as never;
  });
  const onSave = spy.props.onSave;
  let first!: Promise<boolean>, second!: Promise<boolean>;
  await act(async () => {
    first = onSave({ assigned_clan_tag: "#CLAN", kept: true });
    second = onSave({ assigned_clan_tag: "#CLAN", kept: true });
  });
  expect(await second).toBe(false);
  expect(
    vi.mocked(api).mock.calls.filter(([, method]) => method === "PATCH"),
  ).toEqual([
    [
      "/seasons/1/roster/%23PLAYER",
      "PATCH",
      { revision: 1, assigned_clan_tag: "#CLAN", kept: true },
    ],
  ]);
  await act(async () => {
    finish({});
    await first;
  });
  expect(host.textContent).toContain("Undo");
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method ? ({} as never) : (snapshot(3) as never),
  );
  await act(async () =>
    Array.from(host.querySelectorAll("button"))
      .find((b) => b.textContent?.trim() === "Undo")!
      .click(),
  );
  expect(api).toHaveBeenCalledWith("/seasons/1/roster/undo", "POST", {
    revision: 2,
    undo_id: "receipt",
  });
  expect(host.textContent).not.toContain("Undo available");
  expect(changed).toHaveBeenCalledTimes(2);
});
it("reports a successful write followed by failed reload as saved and notifies its page", async () => {
  await render();
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method) return {} as never;
    throw new Error("offline");
  });
  await act(async () => {
    expect(await spy.props.onSave({ kept: true })).toBe(true);
  });
  expect(host.textContent).toContain(
    "Saved. Couldn't refresh. Refresh the page to see the latest.",
  );
  expect(changed).toHaveBeenCalledOnce();
});
it("reloads after 409 so a retry uses the new revision", async () => {
  await render();
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method) throw new ApiError("Roster changed", 409);
    return snapshot(9) as never;
  });
  await act(async () => {
    expect(await spy.props.onSave({ kept: true })).toBe(false);
  });
  vi.mocked(api).mockResolvedValue(snapshot(10));
  await act(async () => {
    await spy.props.onSave({ kept: true });
  });
  expect(api).toHaveBeenLastCalledWith("/seasons/1/roster");
  expect(api).toHaveBeenCalledWith("/seasons/1/roster/%23PLAYER", "PATCH", {
    revision: 9,
    kept: true,
  });
});

it("Declaration uses published snapshots for removed players and blocks every write callback", async () => {
  const published = {
    ...snapshot(),
    accounts: [
      { tag: "#REMOVED", player_name: "Ace" },
      { tag: "#NEXT", player_name: "Blaze" },
    ],
  };
  const setRequest = vi.fn();
  await act(async () =>
    root.render(
      <StaffDetailsPanel
        request={{
          seasonId: "1",
          tag: "#REMOVED",
          viewOnly: "declaration",
          order: ["#REMOVED", "#NEXT"],
          publishedSnapshot: {
            roster: published as any,
            version: 3,
            signupTags: [],
          },
        }}
        setRequest={setRequest}
      />,
    ),
  );
  expect(api).not.toHaveBeenCalled();
  expect(spy.props.account.player_name).toBe("Ace");
  expect(spy.props.publicationNote).toBe(
    "No longer signed up · removed after version 3",
  );
  expect(spy.props.viewOnly).toBe("declaration");
  await act(async () => {
    await spy.props.onSave({ kept: true });
    await spy.props.onRemove();
    await spy.props.onPoolChange("lazy");
  });
  expect(api).not.toHaveBeenCalled();
  spy.props.next();
  expect(setRequest.mock.calls[0][0].tag).toBe("#NEXT");
});

it("keeps a conflicting weight editor mounted until explicit Reload and uses the fresh revision", async () => {
  await render();
  const panel = host.firstElementChild;
  vi.mocked(api).mockClear();
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method) throw new ApiError("Roster changed", 409);
    return snapshot(9) as never;
  });
  await act(async () => {
    expect(
      await spy.props.onSave({ manual_weight: 179000, weight_revision: 2 }),
    ).toBe(false);
  });
  expect(host.firstElementChild).toBe(panel);
  expect(host.textContent).toContain("Changed by someone else · Reload");
  expect(api).toHaveBeenCalledTimes(1);
  expect(changed).not.toHaveBeenCalled();
  await act(async () => {
    await spy.props.onReload();
  });
  expect(host.firstElementChild).toBe(panel);
  expect(host.textContent).not.toContain("Changed by someone else");
  vi.mocked(api).mockResolvedValue(snapshot(10));
  await act(async () => {
    await spy.props.onSave({ manual_weight: 179000, weight_revision: 3 });
  });
  expect(api).toHaveBeenCalledWith("/seasons/1/roster/%23PLAYER", "PATCH", {
    revision: 9,
    manual_weight: 179000,
    weight_revision: 3,
  });
});

it("retains a confirmed filler receipt when follow-up roster read fails", async () => {
  await render();
  vi.mocked(api).mockRejectedValueOnce(new Error("Read offline"));
  await act(async () =>
    spy.props.onFillerChanged({
      tag: "#PLAYER",
      revision: 2,
      roster_filler: true,
      mark_revision: 4,
      undo: { id: 12, label: "Change filler mark" },
    }),
  );
  expect(host.textContent).toContain("Saved. Refresh to see the latest.");
  expect(spy.props.account.roster_filler).toBe(true);
  expect(spy.props.account.roster_filler_revision).toBe(4);
  expect(spy.props.roster.revision).toBe(2);
  expect(host.textContent).toContain("Undo");
  expect(changed).toHaveBeenCalledTimes(1);
});

it("shares the page queue, disables Undo while it works, and uses newest revision for the last saved mark", async () => {
  const { FillerMarkQueue } = await import("./fillerMarkQueue");
  let finish!: (saved: any) => void;
  const wire = vi.fn(
    () =>
      new Promise<any>((resolve) => {
        finish = resolve;
      }),
  );
  const queue = new FillerMarkQueue("1", 9, wire);
  const fillerChanged = vi.fn();
  await act(async () =>
    root.render(
      <StaffDetailsPanel
        request={{
          seasonId: "1",
          tag: "#PLAYER",
          viewOnly: "declaration",
          publishedSnapshot: {
            roster: snapshot(1) as any,
            version: 1,
            signupTags: ["#PLAYER"],
          },
          fillerQueue: queue,
          onFillerChanged: fillerChanged,
        }}
        setRequest={vi.fn()}
      />,
    ),
  );
  expect(spy.props.fillerQueue).toBe(queue);
  await act(async () => {
    queue.enqueue(
      { tag: "#PLAYER", name: "Player", value: false, markRevision: 0 },
      true,
    );
  });
  expect(queue.working).toBe(true);
  await act(async () =>
    finish({
      tag: "#PLAYER",
      revision: 10,
      roster_filler: true,
      mark_revision: 1,
      undo: { id: 88, label: "Change filler mark" },
    }),
  );
  queue.syncRevision(12);
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method
      ? ({
          tag: "#PLAYER",
          revision: 13,
          roster_filler: false,
          mark_revision: 2,
        } as any)
      : snapshot(13),
  );
  const button = [...host.querySelectorAll("button")].find((button) =>
    button.textContent?.includes("Undo"),
  )!;
  expect(button).toBeTruthy();
  await act(async () => button.click());
  expect(api).toHaveBeenCalledWith("/seasons/1/roster/undo", "POST", {
    revision: 12,
    undo_id: 88,
  });
  expect(fillerChanged).toHaveBeenCalledWith({
    tag: "#PLAYER",
    revision: 13,
    roster_filler: false,
    mark_revision: 2,
  });
  expect(queue.working).toBe(false);
  expect(queue.lastSaved).toBeNull();
  expect(queue.latestRevision).toBe(13);
  expect(queue.row("#PLAYER")?.value).toBe(false);
  queue.dispose();
});
it("retains confirmed filler Undo in the page queue when its follow-up read fails", async () => {
  const { FillerMarkQueue } = await import("./fillerMarkQueue");
  const savedDuringPanel = {
    tag: "#PLAYER",
    revision: 10,
    roster_filler: true,
    mark_revision: 1,
    undo: { id: 89, label: "Change filler mark", revision: 10 },
  };
  const queue = new FillerMarkQueue(
    "1",
    9,
    vi.fn().mockResolvedValue(savedDuringPanel),
  );
  const changed = vi.fn();
  await act(async () =>
    root.render(
      <StaffDetailsPanel
        request={{
          seasonId: "1",
          tag: "#PLAYER",
          viewOnly: "declaration",
          publishedSnapshot: {
            roster: snapshot(1) as any,
            version: 1,
            signupTags: ["#PLAYER"],
          },
          fillerQueue: queue,
          onFillerChanged: changed,
        }}
        setRequest={vi.fn()}
      />,
    ),
  );
  await act(async () =>
    queue.enqueue(
      { tag: "#PLAYER", name: "Player", value: false, markRevision: 0 },
      true,
    ),
  );
  vi.mocked(api).mockImplementation(async (_path, method) => {
    if (method)
      return {
        tag: "#PLAYER",
        revision: 11,
        roster_filler: false,
        mark_revision: 2,
      } as any;
    throw new Error("Read unavailable");
  });
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((button) => button.textContent === "Undo")!
      .click(),
  );
  expect(changed).toHaveBeenCalledWith({
    tag: "#PLAYER",
    revision: 11,
    roster_filler: false,
    mark_revision: 2,
  });
  expect(queue.row("#PLAYER")?.value).toBe(false);
  expect(queue.latestRevision).toBe(11);
  expect(host.textContent).toContain("Undone. Refresh to see the latest.");
  queue.dispose();
});

it.each(["#OTHER", "#PLAYER"])(
  "148 does not offer earlier list Undo for %s in newly opened Details",
  async (priorTag) => {
    const { FillerMarkQueue } = await import("./fillerMarkQueue");
    const queue = new FillerMarkQueue("1", 9, vi.fn());
    queue.lastSaved = {
      tag: priorTag,
      revision: 9,
      roster_filler: true,
      mark_revision: 1,
      undo: { id: 77, label: "Change filler mark", revision: 9 },
    };
    await act(async () =>
      root.render(
        <StaffDetailsPanel
          request={{
            seasonId: "1",
            tag: "#PLAYER",
            fillerQueue: queue,
            viewOnly: "declaration",
            publishedSnapshot: {
              roster: snapshot(9) as any,
              version: 1,
              signupTags: ["#PLAYER"],
            },
          }}
          setRequest={vi.fn()}
        />,
      ),
    );
    expect(host.textContent).not.toContain("Undo");
  },
);

it("148 only shows a new save for the open account and dismisses it without reviving", async () => {
  const { FillerMarkQueue } = await import("./fillerMarkQueue");
  let finish!: (saved: any) => void;
  const queue = new FillerMarkQueue(
    "1",
    9,
    vi.fn(() => new Promise<any>((resolve) => (finish = resolve))),
  );
  const roster = {
    ...snapshot(9),
    accounts: [
      { tag: "#PLAYER", player_name: "Panel Player" },
      { tag: "#OTHER", player_name: "Other Player" },
    ],
  };
  const request = {
    seasonId: "1",
    tag: "#PLAYER",
    fillerQueue: queue,
    viewOnly: "declaration" as const,
    publishedSnapshot: {
      roster: roster as any,
      version: 1,
      signupTags: ["#PLAYER", "#OTHER"],
    },
  };
  const show = (tag = "#PLAYER") =>
    root.render(
      <StaffDetailsPanel request={{ ...request, tag }} setRequest={vi.fn()} />,
    );
  await act(async () => show());
  await act(async () => {
    queue.enqueue(
      { tag: "#PLAYER", name: "Panel Player", value: false, markRevision: 0 },
      true,
    );
  });
  await act(async () =>
    finish({
      tag: "#PLAYER",
      revision: 10,
      roster_filler: true,
      mark_revision: 1,
      undo: { id: 88, label: "Change filler mark" },
    }),
  );
  expect(host.textContent).toContain("Panel Player");
  expect(host.textContent).toContain("Undo");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>(
        '[aria-label="Dismiss undo notification"]',
      )!
      .click(),
  );
  await act(async () => show());
  expect(host.textContent).not.toContain("Undo");
  await act(async () => show("#OTHER"));
  expect(host.textContent).not.toContain("Undo");
  await act(async () => show("#PLAYER"));
  expect(host.textContent).not.toContain("Undo");
});
