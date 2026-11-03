// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, type Account, type Season, type Signup } from "./api";
import SavedSignupStatus from "./SavedSignupStatus";
const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mock.api,
}));
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const signups = [
  { tag: "#P2Y", pool: "main", player_name: "Player" },
] as Signup[];
const accounts = [
  { tag: "#P2Y", name: "Player" },
  { tag: "#Q2Y", name: "Other" },
] as Account[];
const season = {
  id: 1,
  label: "November",
  signup_open: true,
  status: "draft",
} as Season;
const props = {
  signups,
  accounts: null,
  season,
  onRemaining: vi.fn(),
  onAssignments: vi.fn(),
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mock.api.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("keeps the same real status/account sections while both reads settle without invented counts or actions", async () => {
  let resolve!: (value: unknown) => void;
  mock.api.mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  await act(async () =>
    root.render(<SavedSignupStatus {...props} accountsLoading />),
  );
  const summary = host.querySelector(".member-signup-summary");
  const accountSummary = host.querySelector(".member-signup-remaining");
  expect(host.textContent).toContain("Checking clan assignments…");
  expect(host.textContent).toContain("Checking linked accounts…");
  expect(host.textContent).not.toContain("All linked accounts");
  expect(accountSummary?.querySelector("button")).toBeNull();
  await act(async () => resolve({ published: null, accounts: [] }));
  expect(host.querySelector(".member-signup-summary")).toBe(summary);
  await act(async () =>
    root.render(<SavedSignupStatus {...props} accounts={accounts} />),
  );
  expect(host.querySelector(".member-signup-remaining")).toBe(accountSummary);
  expect(host.textContent).toContain("1 account not signed up yet");
  expect(accountSummary?.querySelector("button")?.disabled).toBe(false);
  expect(mock.api).toHaveBeenCalledTimes(1);
});
it("keeps a truthful settled account-summary when all linked accounts are signed up", async () => {
  mock.api.mockResolvedValue({ published: null, accounts: [] });
  await act(async () =>
    root.render(
      <SavedSignupStatus {...props} accounts={accounts.slice(0, 1)} />,
    ),
  );
  expect(host.textContent).toContain("All linked accounts are signed up");
  expect(host.querySelector(".member-signup-remaining button")).toBeNull();
});
it("does not claim all signed up when links are unavailable and retains closed-season policy", async () => {
  mock.api.mockResolvedValue({ published: null, accounts: [] });
  await act(async () =>
    root.render(<SavedSignupStatus {...props} accountsUnavailable />),
  );
  expect(host.textContent).toContain("Linked accounts are unavailable");
  expect(host.textContent).not.toContain("All linked accounts");
  expect(host.querySelector(".member-signup-remaining button")).toBeNull();
  await act(async () =>
    root.render(
      <SavedSignupStatus
        {...props}
        accounts={accounts}
        season={{ ...season, signup_open: false }}
      />,
    ),
  );
  expect(host.querySelector(".member-signup-remaining")).toBeNull();
});
it.each([401, 403])(
  "clears the loading component on denied assignments (%s)",
  async (status) => {
    mock.api.mockRejectedValue(new ApiError("private detail", status));
    await act(async () =>
      root.render(<SavedSignupStatus {...props} accounts={accounts} />),
    );
    expect(host.querySelector(".member-signup-summary")).toBeNull();
    expect(host.querySelector('[role="alert"]')?.textContent).toContain(
      "Your account access changed",
    );
    expect(host.textContent).not.toContain("private detail");
  },
);
