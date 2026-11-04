// @vitest-environment happy-dom
import { act, Profiler } from "react";
import MemberSeasonLine from "./MemberSeasonLine";
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
      tag: "#L2Y",
      player_name: "Unknown location",
      pool: "main",
      assigned_clan_tag: "#R2Y",
      assigned_clan_name: "Aurora",
      current_clan_status: "unavailable",
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
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.textContent).toContain("Could not refresh. Showing last update.");
  expect(host.textContent).toContain("Elsewhere");
  expect(host.textContent).not.toContain("upstream secret");
  failure = null;
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.textContent).not.toContain("Could not refresh");
  failure = new ApiError("Access changed", 403);
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
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
  expect(host.textContent).toContain("Sign up for CWL");
  expect(host.textContent).not.toContain("Link an account");
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
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(reads()).toBe(before);
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await new Promise(resolve => setTimeout(resolve, 40)); });
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
  expect(host.textContent).not.toContain("War weight");
  expect(host.textContent).not.toContain("Auto-refresh every 30 seconds");
  expect(
    [...host.querySelectorAll("button")].some(
      (button) => button.textContent === "Pause",
    ),
  ).toBe(false);
  expect(host.querySelector(".eyebrow")).toBeNull();
  failure = new Error("unavailable");
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.textContent).toContain("Retained player");
  expect(host.textContent).toContain("Could not refresh. Showing last update.");
  failure = null;
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.textContent).not.toContain("Could not refresh");
  failure = new ApiError("Sign in again", 401);
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await new Promise(resolve => setTimeout(resolve, 40)); });
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
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.textContent).toContain("November");
  expect(host.textContent).toContain("Could not refresh. Showing last update.");
  expect(host.textContent).not.toContain("private upstream");
  fail = false;
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.textContent).not.toContain("Could not refresh");
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
    text.indexOf("Select Main CWL"),
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
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.textContent).not.toContain("Elsewhere");
  expect(host.textContent).not.toContain("Waiting player");
});

it("keeps an unknown arrival blank and labels May change on its actual clan row", async () => {
  mocks.api.mockResolvedValue(assignment);
  await render(<MemberAssignments seasonId="1" seasons={[season]} />);
  const unknown = [...host.querySelectorAll(".member-clan-row")].find((row) =>
    row.textContent?.includes("Unknown location"),
  )!;
  expect(unknown.textContent).not.toContain("Not in clan yet");
  expect(unknown.querySelector('[role="img"]')).toBeNull();
  expect(host.querySelector(".member-clan-head h2")?.textContent).toContain(
    "May change",
  );
  mocks.api.mockResolvedValue({ ...assignment, draft_changed: false });
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.querySelector(".member-clan-head h2")?.textContent).not.toContain(
    "May change",
  );
});
it("uses the draft/open rule for the member season line", async () => {
  await render(
    <MemberSeasonLine
      season={{
        ...season,
        status: "published",
        signup_open: true,
        signup_deadline: "2026-11-30T12:00:00Z",
      }}
    />,
  );
  expect(host.textContent).toContain("Signups closed");
  expect(host.textContent).not.toContain("Open");
  expect(host.textContent).not.toContain("closes");
});
it("runs Home initial account/context loading while hidden, but skips its hidden repeat", async () => {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
  mocks.accounts.mockResolvedValue({
    accounts: [{ tag: "#P2Y", name: "Hidden-owned player", town_hall: 18 }],
    total: 1,
    updating: false,
    link_instruction: "",
  });
  mocks.api.mockImplementation(async (path: string) =>
    path === "/seasons"
      ? { seasons: [season] }
      : path.includes("my-assignments")
        ? assignment
        : { signups: [] },
  );
  await render(
    <DashboardHome
      session={session}
      seasonId="1"
      seasons={[season]}
      onNavigate={() => {}}
      onStart={() => {}}
    />,
  );
  expect(mocks.accounts).toHaveBeenCalledOnce();
  expect(host.textContent).toContain("Hidden-owned player");
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(mocks.accounts).toHaveBeenCalledOnce();
});
it("refreshes App seasons once on visibilitychange without Home masking a missing listener", async () => {
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: true,
  });
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
  const reads = () =>
    mocks.api.mock.calls.filter(([path]) => path === "/seasons").length;
  const before = reads();
  expect(before).toBe(1);
  Object.defineProperty(document, "hidden", {
    configurable: true,
    value: false,
  });
  await act(async () => { document.dispatchEvent(new Event("visibilitychange")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(reads()).toBe(before + 1);
});
it("never renders assignments before seasons are known", async () => {
  history.replaceState({}, "", "/assignments");
  let resolve!: (value: unknown) => void;
  mocks.api.mockImplementation(async (path: string) =>
    path === "/auth/me"
      ? session
      : path === "/seasons"
        ? new Promise((r) => {
            resolve = r;
          })
        : path.includes("my-assignments")
          ? assignment
          : { dev_fixture: false },
  );
  await render(<App />);
  expect(host.textContent).toContain("Loading seasons");
  expect(host.querySelector(".member-assignments")).toBeNull();
  expect(host.textContent).not.toContain("Staff will make your CWL season");
  await act(async () =>
    resolve({
      seasons: [season],
      member_season: { season_id: 1, revision: 0 },
    }),
  );
  await flush();
  expect(host.textContent).toContain("Elsewhere");
});
it("does not flash link help before a completed account read for a linked member", async () => {
  history.replaceState({}, "", "/signup");
  let resolve!: (value: unknown) => void;
  const seen: boolean[] = [];
  mocks.api.mockImplementation(async (path: string) =>
    path === "/auth/me"
      ? session
      : path === "/seasons"
        ? { seasons: [season], member_season: { season_id: 1, revision: 0 } }
        : path.includes("signups")
          ? { signups: [] }
          : { dev_fixture: false },
  );
  mocks.accounts.mockImplementation(
    () =>
      new Promise((r) => {
        resolve = r;
      }),
  );
  await render(
    <Profiler
      id="signup"
      onRender={() =>
        seen.push(
          [...host.querySelectorAll("h2")].some(
            (h) => h.textContent === "Link an account",
          ),
        )
      }
    >
      <App />
    </Profiler>,
  );
  expect(seen.some(Boolean)).toBe(false);
  expect(host.textContent).not.toContain("Link an account");
  await act(async () =>
    resolve({
      accounts: [{ tag: "#P2Y", name: "Linked", town_hall: 18 }],
      total: 1,
      updating: false,
      link_instruction: "",
    }),
  );
  await flush();
  expect(seen.some(Boolean)).toBe(false);
});
it("shows link help only once after an empty read and hides it during an explicit recheck", async () => {
  history.replaceState({}, "", "/signup");
  let resolve!: (value: unknown) => void;
  mocks.api.mockImplementation(async (path: string) =>
    path === "/auth/me"
      ? session
      : path === "/seasons"
        ? { seasons: [season], member_season: { season_id: 1, revision: 0 } }
        : path.includes("signups")
          ? { signups: [] }
          : { dev_fixture: false },
  );
  mocks.accounts
    .mockResolvedValueOnce({
      accounts: [],
      total: 0,
      updating: false,
      link_instruction: "",
    })
    .mockImplementation(
      () =>
        new Promise((r) => {
          resolve = r;
        }),
    );
  await render(<App />);
  expect(host.querySelectorAll(".account-link-help")).toHaveLength(1);
  const choose = [...host.querySelectorAll("button")].find((b) =>
    b.textContent?.includes("Select Lazy CWL"),
  )!;
  await act(async () => choose.click());
  await flush();
  expect(host.querySelectorAll(".account-link-help")).toHaveLength(1);
  const refresh = [...host.querySelectorAll("button")].find(
    (b) => b.textContent === "Check linked accounts",
  )!;
  await act(async () => refresh.click());
  await flush();
  expect(host.querySelectorAll(".account-link-help")).toHaveLength(0);
  await act(async () =>
    resolve({
      accounts: [{ tag: "#P2Y", name: "Linked", town_hall: 18 }],
      total: 1,
      updating: false,
      link_instruction: "",
    }),
  );
  await flush();
  expect(
    [...host.querySelectorAll("h2")].some(
      (h) => h.textContent === "Link an account",
    ),
  ).toBe(false);
});
it("distinguishes all waiting from a partially waiting publication", async () => {
  const signed = [
    { tag: "#P2Y", pool: "main", assigned_clan_tag: null },
    { tag: "#Q2Y", pool: "lazy", assigned_clan_tag: null },
  ];
  await render(
    <MemberSignupStatus
      signups={signed}
      accounts={[]}
      season={season}
      published
      onRemaining={() => {}}
    />,
  );
  expect(host.textContent).toContain("Your accounts are waiting");
  expect(host.textContent).not.toContain("Some accounts");
  await render(
    <MemberSignupStatus
      signups={[{ ...signed[0], assigned_clan_tag: "#R2Y" }, signed[1]]}
      accounts={[]}
      season={season}
      published
      onRemaining={() => {}}
    />,
  );
  expect(host.textContent).toContain("Some accounts are waiting");
});

it("keeps a known signup season warning small while an explicit stale signup remains refused", async () => {
  history.replaceState({}, "", "/signup");
  let seasonReadFails = false;
  mocks.api.mockImplementation(async (path: string, method?: string) => {
    if (path === "/auth/me") return session;
    if (path === "/seasons") {
      if (seasonReadFails) throw new Error("private season failure");
      return {
        seasons: [season],
        member_season: { season_id: 1, revision: 0 },
      };
    }
    if (path.includes("/signups") && method === "POST")
      throw new ApiError("Signups are closed", 423);
    return path.includes("signups") ? { signups: [] } : { dev_fixture: false };
  });
  mocks.accounts.mockResolvedValue({
    accounts: [{ tag: "#P2Y", name: "Linked member", town_hall: 18 }],
    total: 1,
    updating: false,
    link_instruction: "",
  });
  await render(<App />);
  seasonReadFails = true;
  await act(async () => { window.dispatchEvent(new Event("focus")); await new Promise(resolve => setTimeout(resolve, 40)); });
  await flush();
  expect(host.querySelector(".member-refresh-note")?.getAttribute("role")).toBe(
    "status",
  );
  expect(host.textContent).not.toContain(
    "CWL season availability could not be checked",
  );
  expect(host.textContent).not.toContain("private season failure");
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent?.includes("Select Lazy CWL"))!
      .click(),
  );
  await flush();
  await act(async () =>
    host.querySelector<HTMLInputElement>(".account-select input")!.click(),
  );
  await flush();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "Continue →")!
      .click(),
  );
  await flush();
  await act(async () =>
    [...host.querySelectorAll("button")]
      .find((b) => b.textContent === "Sign up 1 account")!
      .click(),
  );
  await flush();
  expect(host.textContent).toContain("Signups are closed");
  expect(host.querySelector(".completion-card")).toBeNull();
  expect(
    mocks.api.mock.calls.filter(([, method]) => method === "POST"),
  ).toHaveLength(1);
});
