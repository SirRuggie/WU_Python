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
