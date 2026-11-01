// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
import CwlPoolRoles from "./CwlPoolRoles";
import { DashboardPermissions } from "./DashboardPermissions";
const ROLE = "333333333333333333";
const data = () => ({
  roles: [{ id: ROLE, name: "CWL & <safe text>" }],
  pools: (["main", "lazy"] as const).map((pool) => ({
    pool,
    role_id: null as string | null,
    revision: 0,
    member_count: 3,
    member_basis: "members-" + pool,
    progress: {} as Record<string, number>,
    failure: null as string | null,
  })),
});
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockResolvedValue(data());
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});
async function render(owner = true, onDirty = vi.fn()) {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider value={{ owner, permissions: [] }}>
        <CwlPoolRoles onDirty={onDirty} />
      </DashboardPermissions.Provider>,
    ),
  );
  return onDirty;
}
function button(text: string) {
  return [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === text,
  )!;
}
async function choose(role = ROLE) {
  await act(async () => {
    const select = host.querySelector<HTMLSelectElement>("select")!;
    select.value = role;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
}
it("starts both roles off and requires a count confirmation before an exact single write", async () => {
  const dirty = await render();
  expect(host.querySelectorAll("select")).toHaveLength(2);
  expect(
    [...host.querySelectorAll("select")].every((s) => s.value === ""),
  ).toBe(true);
  expect(button("Save Main role").disabled).toBe(true);
  await choose();
  expect(dirty).toHaveBeenLastCalledWith(true);
  await act(async () => button("Save Main role").click());
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Adds role to 3 members",
  );
  expect(vi.mocked(api).mock.calls.filter((c) => c[1] === "POST")).toHaveLength(
    0,
  );
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST"
      ? ((await new Promise<unknown>((done) => (resolve = done))) as never)
      : (data() as never),
  );
  await act(async () => {
    button("Save role").click();
    button("Save role").click();
  });
  const posts = vi.mocked(api).mock.calls.filter((c) => c[1] === "POST");
  expect(posts).toEqual([
    [
      "/pool-roles",
      "POST",
      {
        pool: "main",
        role_id: ROLE,
        revision: 0,
        member_basis: "members-main",
      },
    ],
  ]);
  const saved = data();
  saved.pools[0].role_id = ROLE;
  saved.pools[0].revision = 1;
  await act(async () => resolve(saved));
  expect(dirty).toHaveBeenLastCalledWith(false);
  expect(host.textContent).toContain("Role saved. Updates are queued.");
});
it("cancel sends no write, failed save preserves edits, and permission loss clears protected controls", async () => {
  await render();
  await choose();
  await act(async () => button("Save Main role").click());
  await act(async () => button("Keep current setting").click());
  expect(vi.mocked(api).mock.calls.every((c) => c[1] !== "POST")).toBe(true);
  await act(async () => button("Save Main role").click());
  vi.mocked(api).mockRejectedValueOnce(new ApiError("Signups changed", 409));
  await act(async () => button("Save role").click());
  expect(host.querySelector("select")?.value).toBe(ROLE);
  expect(host.textContent).toContain("Signups changed");
  vi.mocked(api).mockRejectedValueOnce(new ApiError("Access changed", 403));
  await act(async () => button("Refresh roles").click());
  expect(host.querySelector("select")).toBeNull();
  expect(host.textContent).toContain("Access changed");
});
it("unprivileged viewers perform no settings read", async () => {
  await render(false);
  expect(api).not.toHaveBeenCalled();
  expect(host.textContent).toBe("");
});
it("active progress polls only status and stops when work is complete", async () => {
  vi.useFakeTimers();
  const initial = data();
  initial.pools[0].role_id = ROLE;
  initial.pools[0].progress = { pending: 3 };
  vi.mocked(api).mockResolvedValue(initial);
  await render();
  const complete = data();
  complete.pools[0].role_id = ROLE;
  complete.pools[0].progress = { done: 3 };
  vi.mocked(api).mockResolvedValue(complete);
  await act(async () => vi.advanceTimersByTime(5000));
  expect(vi.mocked(api).mock.calls[1][0]).toBe("/pool-roles?status=1");
  expect(host.textContent).toContain("3 of 3 done");
  const count = vi.mocked(api).mock.calls.length;
  await act(async () => vi.advanceTimersByTime(30000));
  expect(api).toHaveBeenCalledTimes(count);
});
it("an old progress response cannot replace a later confirmed role save", async () => {
  vi.useFakeTimers();
  const initial = data();
  initial.pools[0].progress = { pending: 1 };
  vi.mocked(api).mockResolvedValue(initial);
  await render();
  let old!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(async (path) =>
    path.includes("status=1")
      ? ((await new Promise<unknown>((done) => (old = done))) as never)
      : (initial as never),
  );
  await act(async () => vi.advanceTimersByTime(5000));
  await choose();
  await act(async () => button("Save Main role").click());
  const saved = data();
  saved.pools[0].role_id = ROLE;
  saved.pools[0].revision = 1;
  vi.mocked(api).mockResolvedValue(saved);
  await act(async () => button("Save role").click());
  await act(async () => old(initial));
  expect(host.querySelector("select")?.value).toBe(ROLE);
  expect(host.textContent).toContain("Role saved.");
});
it("turns a saved role off using status-only review during a role-choice outage", async () => {
  const offline = {
    ...data(),
    roles: [],
    roles_error: "Role choices unavailable. Refresh or turn off a saved role.",
  };
  offline.pools[0].role_id = ROLE;
  vi.mocked(api).mockResolvedValue(offline);
  await render();
  expect(host.textContent).toContain("Role choices unavailable.");
  await choose("");
  await act(async () => button("Save Main role").click());
  expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toBe("/pool-roles?status=1");
  expect(document.querySelector("dialog")?.textContent).toContain(
    "Existing roles stay",
  );
  const cleared = data();
  vi.mocked(api).mockResolvedValue(cleared);
  await act(async () => button("Turn off role").click());
  expect(vi.mocked(api).mock.calls.at(-1)?.[2]).toMatchObject({
    role_id: null,
  });
  expect(host.textContent).toContain("Role turned off. Existing roles stay.");
});
it("malformed save receipts never report success or discard the role edit", async () => {
  await render();
  await choose();
  await act(async () => button("Save Main role").click());
  vi.mocked(api).mockResolvedValueOnce(null as never);
  await act(async () => button("Save role").click());
  expect(host.textContent).toContain("Save could not be confirmed.");
  expect(host.textContent).not.toContain("Role saved.");
  expect(host.querySelector("select")?.value).toBe(ROLE);
});
it("Seasons scope alone enables this setting, while roster-only access does not", async () => {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider
        value={{ owner: false, permissions: ["cwl_settings"] }}
      >
        <CwlPoolRoles />
      </DashboardPermissions.Provider>,
    ),
  );
  expect(host.querySelectorAll("select")).toHaveLength(2);
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider
        value={{ owner: false, permissions: ["cwl_roster"] }}
      >
        <CwlPoolRoles />
      </DashboardPermissions.Provider>,
    ),
  );
  expect(host.querySelector("select")).toBeNull();
});

it("loads choices only on picker focus and retries a choice outage on Refresh", async () => {
  const blank = { ...data(), roles: undefined };
  vi.mocked(api).mockResolvedValue(blank);
  await render();
  expect(vi.mocked(api).mock.calls.map((call) => call[0])).toEqual([
    "/pool-roles",
  ]);
  expect(host.textContent).not.toContain("unavailable");
  vi.mocked(api).mockResolvedValueOnce({
    ...data(),
    roles: [],
    roles_error: "Role choices unavailable.",
  });
  await act(async () =>
    host.querySelector<HTMLSelectElement>("select")!.focus(),
  );
  expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toBe("/pool-roles?choices=1");
  expect(host.textContent).toContain("Role choices unavailable.");
  vi.mocked(api).mockResolvedValue(data());
  await act(async () => button("Refresh roles").click());
  expect(vi.mocked(api).mock.calls.at(-1)?.[0]).toBe("/pool-roles?choices=1");
  expect(host.textContent).not.toContain("Role choices unavailable.");
});

it("disables unchanged Save during cleanup and clears controls on picker permission loss", async () => {
  const current = { ...data(), roles: undefined };
  current.pools[0].role_id = ROLE;
  current.pools[0].progress = { pending: 1 };
  vi.mocked(api).mockResolvedValue(current);
  await render();
  expect(button("Save Main role").disabled).toBe(true);
  vi.mocked(api).mockRejectedValueOnce(new ApiError("Access changed", 403));
  await act(async () =>
    host.querySelector<HTMLSelectElement>("select")!.focus(),
  );
  expect(host.querySelector("select")).toBeNull();
  expect(host.textContent).toContain("Access changed");
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(0);
});

it("shows the saved name immediately and retains it through local progress polling", async () => {
  vi.useFakeTimers();
  const initial = data();
  initial.pools[0].role_id = ROLE;
  initial.pools[0].progress = { pending: 1 };
  vi.mocked(api).mockResolvedValue({
    ...initial,
    roles: [],
    saved_roles: { main: { name: "CWL & <safe text>", allowed: false } },
  });
  await render();
  expect(host.querySelector("select")?.selectedOptions[0].textContent).toBe(
    "CWL & <safe text>",
  );
  expect(host.textContent).toContain("Saved role is no longer eligible");
  expect(host.querySelector("safe")).toBeNull();
  vi.mocked(api).mockResolvedValue({ ...initial, roles: undefined });
  await act(async () => vi.advanceTimersByTime(5000));
  expect(host.querySelector("select")?.selectedOptions[0].textContent).toBe(
    "CWL & <safe text>",
  );
  expect(host.textContent).toContain("Saved role is no longer eligible");
  await choose("");
  expect(button("Save Main role").disabled).toBe(false);
});

it("offers a plain saved-role fallback and turn-off when names are unavailable", async () => {
  const initial = data();
  initial.pools[0].role_id = ROLE;
  vi.mocked(api).mockResolvedValue({
    ...initial,
    roles: [],
    roles_error: "Role choices unavailable. Refresh or turn off a saved role.",
  });
  await render();
  expect(host.querySelector("select")?.selectedOptions[0].textContent).toBe(
    "Saved role",
  );
  expect(host.textContent).not.toContain(ROLE);
  await choose("");
  expect(button("Save Main role").disabled).toBe(false);
});

it("saving an eligible replacement clears old ineligible metadata immediately", async () => {
  const old = {
    ...data(),
    saved_roles: { main: { name: "Old unsafe role", allowed: false } },
  };
  old.pools[0].role_id = "444444444444444444";
  const saved = {
    ...data(),
    saved_roles: { main: { name: "CWL & <safe text>", allowed: true } },
  };
  saved.pools[0].role_id = ROLE;
  saved.pools[0].revision = 1;
  vi.mocked(api).mockImplementation(async (_path, method) =>
    method === "POST" ? saved : old,
  );
  await render();
  expect(host.textContent).toContain("Saved role is no longer eligible");
  await choose(ROLE);
  await act(async () => button("Save Main role").click());
  await act(async () => button("Save role").click());
  expect(host.textContent).toContain("Role saved. Updates are queued.");
  expect(host.textContent).not.toContain("Saved role is no longer eligible");
});
