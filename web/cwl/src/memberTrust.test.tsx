// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { ApiError, type Season } from "./api";
import MemberAssignments from "./MemberAssignments";
import SavedSignupStatus from "./SavedSignupStatus";
import MemberSignupStatus from "./MemberSignupStatus";
import DashboardHome from "./DashboardHome";
import App from "./App";
import { memberSignupsOpen } from "./memberSeason";
import type { MyAssignments } from "./publication";
const mocks = vi.hoisted(() => ({ api: vi.fn(), accounts: vi.fn() }));
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: mocks.api,
}));
vi.mock("./accountDisplay", async (original) => ({
  ...(await original<object>()),
  loadAccountDisplay: mocks.accounts,
}));
let root: Root, host: HTMLDivElement;
const season = {
  id: 1,
  label: "November",
  status: "draft",
  signup_open: true,
} as Season;
const session = {
  user: { id: "1", username: "Member" },
  can_edit: false,
  is_owner: false,
  csrf_token: "fixture",
  dashboard_permissions: [],
} as never;
const assignment = {
  published: {
    version: 1,
    published_at: "2026-11-01",
    joining_instructions: "",
  },
  visibility: "current",
  draft_changed: true,
  accounts: [
    {
      tag: "#P2Y",
      player_name: "Arrived",
      town_hall: 18,
      pool: "main",
      assigned_clan_tag: "#R2Y",
      assigned_clan_name: "Aurora",
      current_clan_tag: "#R2Y",
      current_clan_status: "current",
      current_clan_checked_at: new Date().toISOString(),
    },
    {
      tag: "#Q2Y",
      player_name: "Elsewhere",
      pool: "lazy",
      assigned_clan_tag: "#R2Y",
      assigned_clan_name: "Aurora",
      current_clan_tag: "#V2Y",
      current_clan_status: "current",
      current_clan_checked_at: new Date().toISOString(),
    },
    {
      tag: "#G2Y",
      player_name: "Waiting player",
      pool: "lazy",
      assigned_clan_tag: null,
    },
  ],
} as unknown as MyAssignments;
const flush = async () => {
  for (let i = 0; i < 5; i++)
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 0));
    });
};
const render = async (element: React.ReactNode) => {
  await act(async () => root.render(element));
  await flush();
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  Object.defineProperty(document, "visibilityState", {
    configurable: true,
    value: "visible",
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mocks.api.mockReset();
  mocks.accounts.mockReset();
  localStorage.clear();
  sessionStorage.clear();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
it("keeps the clan list through failed refresh and recovers; denied access clears it", async () => {
  let failure: Error | null = null;
  mocks.api.mockImplementation(async () => {
    if (failure) throw failure;
    return assignment;
  });
  await render(<MemberAssignments seasonId="1" seasons={[season]} />);
  expect(host.textContent).toContain("Elsewhere");
  expect(host.textContent).toContain("Not in clan yet");
  expect(host.textContent).toContain("✅ = in the right clan");
  expect(host.textContent).toContain("May change");
  expect(host.textContent).toContain("Waiting player");
  failure = new Error("upstream secret unavailable");
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(host.textContent).toContain("Couldn't refresh. Showing last update.");
  expect(host.textContent).toContain("Elsewhere");
  expect(host.textContent).not.toContain("upstream secret");
  failure = null;
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(host.textContent).not.toContain("Couldn't refresh");
  failure = new ApiError("Access changed", 403);
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(host.textContent).not.toContain("Elsewhere");
});
it("keeps initial failure separate and offers closed signup/link help", async () => {
  mocks.api.mockRejectedValueOnce(new Error("first read failed"));
  await render(<MemberAssignments seasonId="1" seasons={[season]} />);
  expect(host.textContent).toContain("first read failed");
  mocks.api.mockResolvedValue({ ...assignment, published: null, accounts: [] });
  await act(async () => host.querySelector("button")!.click());
  await flush();
  expect(host.textContent).toContain("Link an account");
  await render(
    <MemberAssignments
      seasonId="1"
      seasons={[{ ...season, signup_open: false }]}
    />,
  );
  expect(host.textContent).toContain("Ask staff for help.");
});
it("withholds publication claims until the read finishes and always links a partial publication", async () => {
  let resolve!: (value: unknown) => void;
  mocks.api.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await render(
    <SavedSignupStatus
      season={season}
      accounts={[]}
      signups={[{ tag: "#G2Y", player_name: "Waiting", pool: "lazy" } as never]}
      onRemaining={() => {}}
      onAssignments={() => {}}
    />,
  );
  expect(host.textContent).toContain("Checking clan assignments");
  expect(host.textContent).not.toContain("Your clan will show");
  await act(async () => resolve(assignment));
  await flush();
  expect(host.querySelector('a[href="/assignments"]')?.textContent).toContain(
    "My clan assignments",
  );
  await render(
    <MemberSignupStatus
      signups={[]}
      accounts={[]}
      season={{ ...season, status: "active" }}
      onRemaining={() => {}}
    />,
  );
  expect(host.textContent).toContain("Ask staff for help.");
});
it("does not read or claim absent season/signup data while the season is unknown", async () => {
  await render(
    <DashboardHome
      session={session}
      seasonId=""
      seasons={[]}
      seasonsKnown={false}
      onNavigate={() => {}}
      onStart={() => {}}
    />,
  );
  expect(host.textContent).toContain("Loading seasons");
  expect(host.textContent).not.toContain("Not signed up");
  expect(host.textContent).not.toContain("Season coming soon");
  expect(mocks.accounts).not.toHaveBeenCalled();
});
it("loads seasons on first hidden mount and refreshes on visibility, not while hidden", async () => {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  history.replaceState({}, "", "/unrecognized-member-link");
  mocks.api.mockImplementation(async (path: string) =>
    path === "/auth/me"
      ? session
      : path === "/seasons"
        ? { seasons: [season], member_season: { season_id: 1, revision: 0 } }
        : path.includes("my-assignments")
          ? assignment
          : path.includes("signups")
            ? { signups: [] }
            : { dev_fixture: false },
  );
  mocks.accounts.mockResolvedValue({
    accounts: [],
    link_instruction: "",
    total: 0,
    updating: false,
  });
  await render(<App />);
  const reads = () =>
    mocks.api.mock.calls.filter(([path]) => path === "/seasons").length;
  expect(reads()).toBeGreaterThan(0);
  expect(host.textContent).toContain("November");
  expect(host.textContent).not.toContain("No CWL season available");
  const before = reads();
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(reads()).toBe(before);
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await flush();
  expect(reads()).toBeGreaterThan(before);
});
it("shares exactly one signup-open rule for draft/open only", () => {
  expect(memberSignupsOpen(season)).toBe(true);
  expect(memberSignupsOpen({ ...season, status: "active" })).toBe(false);
  expect(memberSignupsOpen({ ...season, signup_open: false })).toBe(false);
  expect(memberSignupsOpen(undefined)).toBe(false);
});
it("retains Home account and signup data through refresh failure, then recovers and clears on 401", async () => {
  let failure: Error | null = null;
  mocks.accounts.mockResolvedValue({
    accounts: [{ tag: "#P2Y", name: "Retained player", town_hall: 18 }],
    total: 1,
    updating: false,
    link_instruction: "",
  });
  mocks.api.mockImplementation(async (path: string) => {
    if (failure) throw failure;
    return path === "/seasons"
      ? { seasons: [season] }
      : path.includes("my-assignments")
        ? assignment
        : {
            signups: [
              { tag: "#P2Y", player_name: "Retained player", pool: "main" },
            ],
          };
  });
  await render(
    <DashboardHome
      session={session}
      seasonId="1"
      seasons={[season]}
      onNavigate={() => {}}
      onStart={() => {}}
    />,
  );
  expect(host.textContent).toContain("Retained player");
  failure = new Error("unavailable");
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await flush();
  expect(host.textContent).toContain("Retained player");
  expect(host.textContent).toContain("Couldn't refresh. Showing last update.");
  failure = null;
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await flush();
  expect(host.textContent).not.toContain("Couldn't refresh");
  failure = new ApiError("Sign in again", 401);
  await act(async () => document.dispatchEvent(new Event("visibilitychange")));
  await flush();
  expect(host.textContent).not.toContain("Retained player");
});
it("keeps the known Home season after a failed focus refresh and recovers", async () => {
  history.replaceState({}, "", "/");
  let fail = false;
  mocks.api.mockImplementation(async (path: string) => {
    if (path === "/auth/me") return session;
    if (path === "/seasons") {
      if (fail) throw new Error("private upstream failure");
      return {
        seasons: [season],
        member_season: { season_id: 1, revision: 0 },
      };
    }
    if (path.includes("my-assignments")) return assignment;
    return path.includes("signups") ? { signups: [] } : { dev_fixture: false };
  });
  mocks.accounts.mockResolvedValue({
    accounts: [],
    total: 0,
    updating: false,
    link_instruction: "",
  });
  await render(<App />);
  fail = true;
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(host.textContent).toContain("November");
  expect(host.textContent).toContain("Couldn't refresh. Showing last update.");
  expect(host.textContent).not.toContain("private upstream");
  fail = false;
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(host.textContent).not.toContain("Couldn't refresh");
});
it("puts linking help before the pool choice when a completed read has no linked accounts", async () => {
  history.replaceState({}, "", "/signup");
  mocks.api.mockImplementation(async (path: string) =>
    path === "/auth/me"
      ? session
      : path === "/seasons"
        ? { seasons: [season], member_season: { season_id: 1, revision: 0 } }
        : path.includes("signups")
          ? { signups: [] }
          : { dev_fixture: false },
  );
  mocks.accounts.mockResolvedValue({
    accounts: [],
    total: 0,
    updating: false,
    link_instruction: "",
  });
  await render(<App />);
  const text = host.textContent!;
  expect(text).toContain("Link an account");
  expect(text.indexOf("Link an account")).toBeLessThan(
    text.indexOf("Choose Main CWL"),
  );
});

it("clears assignments when a later season read loses permission", async () => {
  history.replaceState({}, "", "/assignments");
  let denied = false;
  mocks.api.mockImplementation(async (path: string) => {
    if (path === "/auth/me") return session;
    if (path === "/seasons") {
      if (denied) throw new ApiError("Access changed", 403);
      return {
        seasons: [season],
        member_season: { season_id: 1, revision: 0 },
      };
    }
    return path.includes("my-assignments")
      ? assignment
      : { dev_fixture: false };
  });
  await render(<App />);
  expect(host.textContent).toContain("Elsewhere");
  denied = true;
  await act(async () => window.dispatchEvent(new Event("focus")));
  await flush();
  expect(host.textContent).not.toContain("Elsewhere");
  expect(host.textContent).not.toContain("Waiting player");
});
