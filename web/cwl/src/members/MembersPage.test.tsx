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
