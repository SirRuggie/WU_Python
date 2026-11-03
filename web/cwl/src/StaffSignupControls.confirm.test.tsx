// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const fixture = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: fixture.api,
}));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
vi.mock("./useSignupAction", () => ({
  default: () => ({
    hiddenOpen: false,
    busy: false,
    error: "",
    notice: "",
    dialog: null,
    visibilityCheck: null,
    begin: () => {},
  }),
}));
vi.mock("./MemberPicker", () => ({
  default: ({ onChange }: { onChange: (id: string) => void }) => (
    <button onClick={() => onChange("123456789012345678")}>
      Choose fixture member
    </button>
  ),
}));
vi.mock("./StaffTagSignup", () => ({ default: () => null }));
import StaffSignupControls from "./StaffSignupControls";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const changed = vi.fn();
const button = (text: string, within: ParentNode = document) =>
  [...within.querySelectorAll("button")].find(
    (b) => b.textContent?.trim() === text,
  )!;
const writes = () =>
  fixture.api.mock.calls.filter((call) => call[1] && call[1] !== "GET");
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
  fixture.api
    .mockReset()
    .mockImplementation(async (_path: string, method?: string) =>
      method === "POST"
        ? { count: 1 }
        : {
            accounts: [
              {
                tag: "#PYY",
                name: "Fixture",
                current_clan_name: "Family",
                signed_up_pool: null,
              },
            ],
          },
    );
  changed.mockReset().mockResolvedValue(undefined);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () =>
    root.render(
      <StaffSignupControls
        season={{
          id: 1,
          label: "November",
          status: "draft",
          signup_open: true,
        }}
        onChanged={changed}
        onDirty={() => {}}
        onBusy={() => {}}
      />,
    ),
  );
  await act(async () => button("Add signup").click());
  await act(async () => button("Choose fixture member").click());
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
async function prepare() {
  const pool = [...document.querySelectorAll(".roster-menu-trigger")].find(
    (b) => b.textContent?.includes("CWL type"),
  ) as HTMLButtonElement;
  if (!pool) throw Error("CWL pool control missing");
  await act(async () => pool.click());
  const main = [
    ...document.querySelectorAll<HTMLElement>('[role="menuitem"]'),
  ].find((e) => e.textContent?.trim() === "Main CWL")!;
  await act(async () => {
    main.dispatchEvent(
      new MouseEvent("mousedown", { bubbles: true, button: 0 }),
    );
    main.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, button: 0 }));
    main.click();
  });
  const checkbox = document.querySelector<HTMLInputElement>(
    'input[type="checkbox"]',
  )!;
  await act(async () => checkbox.click());
}
it("adding a signup requires confirmation, Cancel writes zero, double confirmation writes once", async () => {
  await prepare();
  const add = [...document.querySelectorAll("button")].find((b) =>
    /^Add 1 account/.test(b.textContent?.trim() || ""),
  )!;
  await act(async () => add.click());
  expect(writes()).toHaveLength(0);
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(writes()).toHaveLength(0);
  await act(async () => {
    add.click();
    add.click();
  });
  await act(async () => {
    const confirm = button(
      "Add accounts",
      document.querySelector(".confirm-dialog")!,
    );
    confirm.click();
    confirm.click();
  });
  expect(writes()).toHaveLength(1);
  expect(writes()[0]).toEqual([
    "/seasons/1/staff-signups",
    "POST",
    {
      user_id: "123456789012345678",
      pool: "main",
      accounts: [{ tag: "#PYY", prefer_crystal_1_or_lower: false }],
    },
  ]);
});
it("discard Cancel retains member selection and confirmed discard performs no write", async () => {
  await act(async () =>
    button("Cancel", document.querySelector(".staff-signup-form")!).click(),
  );
  expect(document.querySelector(".confirm-dialog")).not.toBeNull();
  await act(async () =>
    button("Cancel", document.querySelector(".confirm-dialog")!).click(),
  );
  expect(document.body.textContent).toContain("Choose fixture member");
  await act(async () =>
    button("Cancel", document.querySelector(".staff-signup-form")!).click(),
  );
  await act(async () =>
    button(
      "Discard signup",
      document.querySelector(".confirm-dialog")!,
    ).click(),
  );
  expect(document.querySelector(".staff-signup-form")).toBeNull();
  expect(writes()).toHaveLength(0);
});
