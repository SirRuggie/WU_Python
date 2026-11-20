// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import DashboardHome from "./DashboardHome";
import HomeSignupSummary from "./HomeSignupSummary";
import { clearJourneyState } from "./journeyState";
import { clearSnapshots } from "./snapshotCache";
import { ApiError, type Account, type Session, type Season } from "./api";
const mocks = vi.hoisted(() => ({ api: vi.fn(), accounts: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mocks.api,
}));
vi.mock("./accountDisplay", async (original) => ({
  ...(await original<object>()),
  loadAccountDisplay: mocks.accounts,
}));
vi.mock("./TownHallIcon", () => ({ default: () => <span>TH</span> }));
let host: HTMLDivElement, root: Root;
const season = {
  id: 1,
  label: "Fixture",
  status: "draft",
  signup_open: true,
} as Season;
const session = {
  user: { id: "fixture", username: "Fixture" },
  csrf_token: "session-a",
  can_edit: false,
  is_owner: false,
} as Session;
const accounts = (count: number) =>
  Array.from(
    { length: count },
    (_, i) =>
      ({
        tag: "#P2Y" + i,
        name: "Fixture " + i,
        town_hall: 18,
        current_clan_tag: null,
        current_clan_name: null,
        verified: true,
        lazy_eligible: true,
        family_clan_status: "unknown",
      }) as Account,
  );
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  clearJourneyState();
  clearSnapshots();
  mocks.api.mockReset();
  mocks.accounts.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});
it("uses a real initiallyclosed signupdisclosure remembered onlyinmemory per session", async () => {
  const props = {
    signups: [{ tag: "#P2Y", pool: "main", player_name: "Saved fixture" }],
    accounts: accounts(3),
    season,
    sessionKey: "session-a",
    onRemaining: vi.fn(),
  };
  await act(async () => root.render(<HomeSignupSummary {...props} />));
  let disclosure = host.querySelector("details")!;
  expect(disclosure.open).toBe(false);
  expect(disclosure.querySelector("summary")!.textContent).toContain(
    "Signed up · 1 of 3 accounts",
  );
  expect(host.textContent).not.toContain("Saved fixture");
  await act(async () => {
    disclosure.open = true;
    disclosure.dispatchEvent(new Event("toggle"));
  });
  expect(host.textContent).toContain("Saved fixture");
  await act(async () =>
    root.render(
      <HomeSignupSummary key="session-b" {...props} sessionKey="session-b" />,
    ),
  );
  expect(host.querySelector("details")!.open).toBe(false);
});
it.each([3, 10, 47])(
  "showslocalFilteraccounts onlyabove10 (%s) and staffshortcuts beforeMyaccounts",
  async (count) => {
    mocks.accounts.mockResolvedValue({
      accounts: accounts(count),
      link_instruction: "Fixture",
      total: count,
      updating: false,
    });
    mocks.api.mockImplementation(async (path: string) =>
      path === "/approved-clans"
        ? { clans: [] }
        : path === "/seasons"
          ? { seasons: [season] }
          : path.endsWith("/signups")
            ? { signups: [] }
            : path.endsWith("/my-assignments")
              ? {
                  accounts: [],
                  published: null,
                  visibility: "current",
                  draft_changed: false,
                }
              : Promise.reject(new Error("Unexpected fixture path " + path)),
    );
    await act(async () =>
      root.render(
        <DashboardHome
          session={{ ...session, can_edit: true }}
          seasonId="1"
          seasons={[season]}
          onNavigate={vi.fn()}
          onStart={vi.fn()}
        />,
      ),
    );
    expect(host.textContent.includes("Filter accounts")).toBe(count > 10);
    const staff = host.querySelector(".hub-staff")!,
      heading = [...host.querySelectorAll("h2")].find(
        (n) => n.textContent === "My accounts",
      )!;
    expect(
      Boolean(
        staff.compareDocumentPosition(heading) &
        Node.DOCUMENT_POSITION_FOLLOWING,
      ),
    ).toBe(true);
    expect(host.querySelectorAll(".game-search input")).toHaveLength(1);
  },
);
it("does not renderstaffshortcuts forordinarymembers", async () => {
  mocks.accounts.mockResolvedValue({
    accounts: accounts(3),
    link_instruction: "Fixture",
    total: 3,
    updating: false,
  });
  mocks.api.mockImplementation(async (path: string) =>
    path === "/seasons" ? { seasons: [] } : { accounts: [], published: null },
  );
  await act(async () =>
    root.render(
      <DashboardHome
        session={session}
        seasonId=""
        seasons={[]}
        onNavigate={vi.fn()}
        onStart={vi.fn()}
      />,
    ),
  );
  expect(host.querySelector(".hub-staff")).toBeNull();
  expect(
    mocks.api.mock.calls.filter(([path]) => path === "/approved-clans"),
  ).toHaveLength(0);
});

function home(sessionValue: Session) {
  return (
    <DashboardHome
      session={sessionValue}
      seasonId=""
      seasons={[]}
      onNavigate={vi.fn()}
      onStart={vi.fn()}
    />
  );
}
function searchInput(value: string) {
  const field = host.querySelector(".game-search input")!;
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}
function normalAccounts() {
  return {
    accounts: accounts(3),
    link_instruction: "Fixture",
    total: 3,
    updating: false,
  };
}
it("loads the editor directory once and matches a clan absent from linked accounts", async () => {
  vi.useFakeTimers();
  mocks.accounts.mockResolvedValue(normalAccounts());
  mocks.api.mockImplementation(async (path: string) =>
    path === "/seasons"
      ? { seasons: [] }
      : path === "/approved-clans"
        ? { clans: [{ tag: "#C2Y", name: "Unlinked approved clan" }] }
        : path.startsWith("/search?")
          ? { results: [] }
          : Promise.reject(new Error(path)),
  );
  await act(async () => root.render(home({ ...session, can_edit: true })));
  await act(async () => searchInput("Unlinked"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.querySelector(".search-result")!.textContent).toContain(
    "Unlinked approved clan",
  );
  expect(host.querySelector(".search-result")!.textContent).toContain("Family");
  await act(async () => searchInput("approved"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(
    mocks.api.mock.calls.filter(([path]) => path === "/approved-clans"),
  ).toHaveLength(1);
});
it("keeps Home usable when the authorized directory is unavailable", async () => {
  mocks.accounts.mockResolvedValue(normalAccounts());
  mocks.api.mockImplementation(async (path: string) =>
    path === "/seasons"
      ? { seasons: [] }
      : Promise.reject(new Error("Directory unavailable")),
  );
  await act(async () => root.render(home({ ...session, can_edit: true })));
  expect(host.querySelector(".game-search")!.textContent).toContain(
    "Some family results could not load.",
  );
  expect(host.textContent).toContain("Fixture 0");
});
it("clears family data on directory denial and rejects later account completion", async () => {
  let rejectDirectory: (value: unknown) => void = () => {};
  let finishAccounts: (value: unknown) => void = () => {};
  mocks.accounts.mockImplementation(
    () =>
      new Promise((resolve) => {
        finishAccounts = resolve;
      }),
  );
  mocks.api.mockImplementation((path: string) =>
    path === "/approved-clans"
      ? new Promise((_, reject) => {
          rejectDirectory = reject;
        })
      : Promise.resolve({ seasons: [] }),
  );
  await act(async () => root.render(home({ ...session, can_edit: true })));
  await act(async () => rejectDirectory(new ApiError("Expired", 401)));
  await act(async () => finishAccounts(normalAccounts()));
  expect(host.textContent).toContain(
    "Your dashboard access changed. Sign in again.",
  );
  expect(host.textContent).not.toContain("Fixture 0");
});
it("does not publish the previous session directory after an authorization change", async () => {
  vi.useFakeTimers();
  let finishOld: (value: unknown) => void = () => {};
  mocks.accounts.mockResolvedValue(normalAccounts());
  mocks.api.mockImplementation((path: string) =>
    path === "/approved-clans"
      ? new Promise((resolve) => {
          finishOld = resolve;
        })
      : Promise.resolve(
          path === "/seasons" ? { seasons: [] } : { results: [] },
        ),
  );
  await act(async () => root.render(home({ ...session, can_edit: true })));
  await act(async () =>
    root.render(
      home({ ...session, csrf_token: "member-session", can_edit: false }),
    ),
  );
  await act(async () =>
    finishOld({ clans: [{ tag: "#C2Y", name: "Private old directory" }] }),
  );
  await act(async () => searchInput("Private"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.textContent).not.toContain("Private old directory");
  expect(
    mocks.api.mock.calls.filter(([path]) => path === "/approved-clans"),
  ).toHaveLength(1);
});
