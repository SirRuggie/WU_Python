// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
vi.mock("../api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api } from "../api";
import { DashboardPermissions } from "../DashboardPermissions";
import MembersPage from "./MembersPage";
const ROLE = "333333333333333333";
const member = (index: number) => ({
  discord_id: String(111111111111111111n + BigInt(index)),
  name: `Person ${index}`,
  username: `user${index}`,
  nickname: `Person ${index}`,
  bot: false,
  status: "Missing",
  profile: null,
  parsed: null,
  skip_reason: null,
  role_ids: [],
});
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
  vi.mocked(api).mockImplementation(async (path) => {
    if (path === "/manage/members")
      return {
        members: [
          ...Array.from({ length: 26 }, (_, i) => member(i)),
          { ...member(26), name: "Fixture bot", bot: true },
        ],
        roles: [{ id: ROLE, name: "Officer" }],
        manageable_roles: [{ id: ROLE, name: "Officer" }],
        countries: [],
        zones: [],
        permission: "member_roles",
      };
    if (path.includes("active=1")) return { runs: [] };
    throw new Error("Unexpected fixture API: " + path);
  });
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function render(allowed = true) {
  await act(async () =>
    root.render(
      <DashboardPermissions.Provider
        value={{ owner: false, permissions: allowed ? ["member_roles"] : [] }}
      >
        <MembersPage onDirty={() => {}} />
      </DashboardPermissions.Provider>,
    ),
  );
}
const button = (text: string) =>
  [...host.querySelectorAll("button")].find(
    (item) => item.textContent === text,
  )!;
it("viewer without member_roles makes no protected directory or run request", async () => {
  await render(false);
  expect(api).not.toHaveBeenCalled();
  expect(host.querySelectorAll("input")).toHaveLength(0);
});
it("Select page counts exactly the 25 visible people and hides bots", async () => {
  await render();
  expect(host.textContent).toContain("Showing 1-25 of 26");
  expect(host.textContent).not.toContain("Fixture bot");
  const page = host.querySelector<HTMLInputElement>(
    'input[aria-label="Select page"]',
  )!;
  await act(async () => page.click());
  expect(host.querySelectorAll(".members-person input:checked")).toHaveLength(
    25,
  );
  expect(host.textContent).toContain("25 selected");
  expect(vi.mocked(api).mock.calls.every((call) => call[1] !== "POST")).toBe(
    true,
  );
  await act(async () => button("Select none").click());
  expect(host.textContent).not.toContain("25 selected");
});
it("a partial selection survives search and reports the hidden count", async () => {
  await render();
  const checkbox = host.querySelector<HTMLInputElement>(
    ".members-person input",
  )!;
  await act(async () => checkbox.click());
  expect(
    host.querySelector<HTMLInputElement>('input[aria-label="Select page"]')!
      .indeterminate,
  ).toBe(true);
  const search = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    const setter = Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!;
    setter.call(search, "user25");
    search.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.textContent).toContain("1 selected · 1 hidden");
  expect(host.textContent).toContain("Person 25");
});

it.each(["profile text", "duplicate role", "country choices"])(
  "malformed directory %s cannot render protected controls and recovers with Refresh",
  async (bad) => {
    let healthy = false;
    vi.mocked(api).mockImplementation(async (path) => {
      if (path !== "/manage/members") return { runs: [] };
      const roles = [{ id: ROLE, name: "Officer" }];
      const person = member(0);
      const result = {
        members: [person],
        roles,
        manageable_roles: roles,
        countries: [],
        zones: [],
        permission: "member_roles",
      };
      if (healthy) return result;
      if (bad === "profile text")
        return {
          ...result,
          members: [
            {
              ...person,
              profile: {
                zone_id: "gmt-5",
                gmt_label: {},
                utc_offset_minutes: -300,
                country: "US",
                flag: "🇺🇸",
                revision: 1,
                source: "staff",
                name_source_tag: null,
              },
            },
          ],
        };
      if (bad === "duplicate role")
        return { ...result, roles: [...roles, ...roles] };
      return {
        ...result,
        countries: [
          { code: "US", label: "United States", flag: "🇺🇸", zones: [{}] },
        ],
      };
    });
    await render();
    expect(host.textContent).toContain("Members are unavailable");
    expect(host.querySelector(".members-person")).toBeNull();
    healthy = true;
    await act(async () => button("Refresh members").click());
    expect(host.querySelectorAll(".members-person")).toHaveLength(1);
    expect(vi.mocked(api).mock.calls.some((call) => call[1] === "POST")).toBe(
      false,
    );
  },
);

it("one-person role change refreshes immediately and Undo sends the exact post-change guard", async () => {
  let roleIds: string[] = [];
  let prepared: {
    operation: string;
    selected: string[];
    role: { id: string; name: string; protected: boolean };
    count: number;
    token: string;
  };
  let current: object;
  const confirmations: unknown[] = [],
    previews: { guard_role_ids?: string[] }[] = [];
  vi.mocked(api).mockImplementation(async (path, method, body) => {
    if (path === "/manage/members")
      return {
        members: [{ ...member(0), role_ids: [...roleIds] }],
        roles: [{ id: ROLE, name: "Officer" }],
        manageable_roles: [{ id: ROLE, name: "Officer" }],
        countries: [],
        zones: [],
        permission: "member_roles",
      };
    if (path.includes("active=1")) return { runs: [] };
    if (path.endsWith("role-preview")) {
      const value = body as {
        member_ids: string[];
        operation: string;
        guard_role_ids?: string[];
      };
      previews.push(value);
      prepared = {
        token: "review" + previews.length,
        count: value.member_ids.length,
        selected: [...value.member_ids],
        operation: value.operation,
        role: { id: ROLE, name: "Officer", protected: false },
      };
      return prepared;
    }
    if (path.endsWith("role-confirm") && method === "POST") {
      confirmations.push(body);
      const before = [...roleIds];
      roleIds = prepared!.operation === "add" ? [ROLE] : [];
      current = {
        run_id: "run" + confirmations.length,
        state: "done",
        rows: [
          {
            discord_id: member(0).discord_id,
            status: "done",
            message: "Changed",
            changed: true,
            role_id: ROLE,
            operation: prepared!.operation,
            expected_role_ids: before,
          },
        ],
      };
      return { run_id: "run" + confirmations.length, state: "done" };
    }
    if (path.includes("/role-runs/run")) return current!;
    throw new Error("Unexpected sample call: " + path);
  });
  await render();
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".members-person-open")!.click(),
  );
  const toggle = () =>
    document.querySelector<HTMLInputElement>('input[role="switch"]')!;
  await act(async () => toggle().click());
  expect(confirmations).toHaveLength(1);
  expect(toggle().checked).toBe(true);
  const undo = [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (item) => item.textContent === "Undo",
  )!;
  expect(undo).toBeTruthy();
  await act(async () => undo.click());
  expect(confirmations).toHaveLength(2);
  expect(previews[1].guard_role_ids).toEqual([ROLE]);
  expect(toggle().checked).toBe(false);
  expect(
    [...document.querySelectorAll("button")].some(
      (item) => item.textContent === "Undo",
    ),
  ).toBe(false);
});

it("switching people keeps the existing detail history entry and confirms a dirty editor", async () => {
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  const original = vi.mocked(api).getMockImplementation()!;
  vi.mocked(api).mockImplementation(async (...args) =>
    args[0].endsWith("/choices")
      ? { accounts: [], complete: true }
      : original(...args),
  );
  await render();
  const people = host.querySelectorAll<HTMLButtonElement>(
    ".members-person-open",
  );
  await act(async () => people[0].click());
  const firstMarker = history.state.wuActionPanel;
  const firstAccount = new URLSearchParams(location.search).get("account");
  const edit = [...document.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === "Edit time zone and flag",
  )!;
  await act(async () => edit.click());
  await act(async () => {
    const input = document.querySelector<HTMLInputElement>(".mt-editor input")!;
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Draft name");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => people[1].click());
  expect(new URLSearchParams(location.search).get("account")).toBe(
    firstAccount,
  );
  expect(document.querySelector(".confirm-dialog")?.textContent).toContain(
    "Discard unsaved changes",
  );
  const cancel = [
    ...document.querySelectorAll<HTMLButtonElement>(".confirm-dialog button"),
  ].find((b) => b.textContent === "Cancel")!;
  await act(async () => cancel.click());
  expect(
    document.querySelector<HTMLInputElement>(".mt-editor input")?.value,
  ).toBe("Draft name");
  await act(async () => people[1].click());
  const discard = [
    ...document.querySelectorAll<HTMLButtonElement>(".confirm-dialog button"),
  ].find((b) => b.textContent === "Discard changes")!;
  await act(async () => discard.click());
  expect(new URLSearchParams(location.search).get("account")).not.toBe(
    firstAccount,
  );
  expect(history.state.wuActionPanel).toBe(firstMarker);
  expect(document.querySelector(".mt-editor")).toBeNull();
  expect(document.querySelectorAll(".details-frame")).toHaveLength(1);
});
