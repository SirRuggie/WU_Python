// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import GameSearch from "./GameSearch";
import { ApiError, type Account, type Session } from "./api";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./TownHallIcon", () => ({ default: () => <span>TH</span> }));
vi.mock("./MemberDetailActivity", () => ({
  default: () => <span>Family activity</span>,
}));
let host: HTMLDivElement, root: Root;
const session = {
  user: { id: "fixture-user" },
  csrf_token: "fixture",
  can_edit: false,
} as Session;
const family = {
  kind: "player",
  tag: "#P2Y",
  name: "Family fixture",
  source: "family",
  town_hall: 18,
};
const clan = {
  kind: "clan",
  tag: "#C2Y",
  name: "Public fixture",
  source: "clash",
  level: 18,
  members: 22,
  public_war_log: true,
};
function input(value: string) {
  const field = host.querySelector("input")!;
  Object.getOwnPropertyDescriptor(
    HTMLInputElement.prototype,
    "value",
  )!.set!.call(field, value);
  field.dispatchEvent(new Event("input", { bubbles: true }));
}
const owned = {
  ...family,
  current_clan_tag: null,
  current_clan_name: null,
  town_hall: 18,
  verified: true,
  lazy_eligible: true,
  lazy_ineligible_reason: null,
  family_clan_status: "unknown",
} as Account;
async function mount(accounts: Account[] = [owned]) {
  await act(async () =>
    root.render(
      <GameSearch session={session} accounts={accounts} onTasks={vi.fn()} />,
    ),
  );
}

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
  api.mockReset();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  HTMLDialogElement.prototype.showModal = function () {
    this.open = true;
  };
  HTMLDialogElement.prototype.close = function () {
    this.open = false;
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  document.querySelectorAll("dialog").forEach((n) => n.remove());
  vi.useRealTimers();
});
it("debounces350ms and Enter replaces its timer without duplicate calls", async () => {
  api.mockResolvedValue({ results: [] });
  await mount();
  await act(async () => input("Fixture"));
  await act(async () => vi.advanceTimersByTime(349));
  expect(api).not.toHaveBeenCalled();
  await act(async () =>
    host
      .querySelector("form")!
      .dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })),
  );
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTime(500));
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => input(" FIXTURE "));
  await act(async () => vi.advanceTimersByTime(500));
  expect(api).toHaveBeenCalledTimes(1);
});
it("orders family beforeClash and opens one public-details dialog with safe fields", async () => {
  api.mockImplementation(async (path: string) =>
    path.startsWith("/search/details") ? clan : { results: [clan, family] },
  );
  await mount();
  await act(async () => input("fixture"));
  await act(async () => vi.advanceTimersByTime(350));
  const rows = [...host.querySelectorAll(".search-result")];
  expect(rows[0].textContent).toContain("Family fixture");
  expect(rows[1].textContent).toContain("Clash");
  expect(rows[0].querySelector("a")?.getAttribute("href")).toContain(
    "filter=%23P2Y",
  );
  await act(async () => rows[1].querySelector("button")!.click());
  expect(document.querySelectorAll("dialog")).toHaveLength(1);
  expect(document.querySelector("dialog")!.textContent).toContain(
    "Public war log",
  );
  expect(document.querySelector("dialog")!.textContent).not.toContain(
    "Family activity",
  );
  expect(document.querySelector("dialog a")!.getAttribute("href")).toMatch(
    /^https:\/\/link\.clashofclans\.com\//,
  );
});
it("drops stale search responses after a new query", async () => {
  let resolve: (v: unknown) => void = () => {};
  api.mockImplementation((path: string) =>
    path.includes("first")
      ? new Promise((r) => (resolve = r))
      : Promise.resolve({ results: [clan] }),
  );
  await mount();
  await act(async () => input("first"));
  await act(async () => vi.advanceTimersByTime(350));
  await act(async () => input("second"));
  await act(async () => vi.advanceTimersByTime(350));
  await act(async () => resolve({ results: [family] }));
  expect(host.textContent).toContain("Public fixture");
  expect(host.textContent).not.toContain("Family fixture");
});
it("keeps familyfallback visible with oneerroraction and displays429 knownstate", async () => {
  api.mockResolvedValue({
    results: [family],
    errors: ["Clash data is unavailable. Try again."],
  });
  await mount();
  await act(async () => input("fixture"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.textContent).toContain("Family fixture");
  expect(
    [...host.querySelectorAll("button")].filter(
      (b) => b.textContent === "Try again",
    ),
  ).toHaveLength(1);
  api.mockRejectedValue(new ApiError("raw response", 429));
  await act(async () => input("another"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.textContent).toContain("Too many searches. Wait a minute.");
  expect(host.querySelector(".empty-state")).toBeNull();
});
it("renders external text as text and rejects unsafe badge URLs", async () => {
  api.mockResolvedValue({
    results: [
      {
        ...clan,
        name: "<img src=x onerror=bad()>",
        badge_url: "javascript:bad",
      },
    ],
  });
  await mount();
  await act(async () => input("fixture"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.textContent).toContain("<img src=x onerror=bad()>");
  expect(host.querySelector(".search-result img")).toBeNull();
});
it("clears private results when search auth expires", async () => {
  api.mockResolvedValue({ results: [family] });
  await mount();
  await act(async () => input("fixture"));
  await act(async () => vi.advanceTimersByTime(350));
  api.mockRejectedValue(new ApiError("Sign in required", 401));
  await act(async () => input("different"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.textContent).not.toContain("Family fixture");
  expect(host.textContent).toContain("Sign in required");
});

it("never shows linked account or staff facts for a public player", async () => {
  const stranger = {
    kind: "player",
    tag: "#V2Y",
    name: "Public stranger",
    source: "clash",
    town_hall: 18,
    clan_name: "Public clan",
    clan_tag: "#R2Y",
    trophies: 3210,
  };
  api.mockImplementation(async (path: string) =>
    path.startsWith("/search/details") ? stranger : { results: [stranger] },
  );
  await mount();
  await act(async () => input("#V2Y"));
  await act(async () => vi.advanceTimersByTime(350));
  const row = host.querySelector(".search-result")!;
  expect(row.querySelector("a")).toBeNull();
  await act(async () => row.querySelector("button")!.click());
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("Trophies");
  for (const text of [
    "Linked player",
    "Roster weight",
    "Your Discord account",
    "Family status unknown",
    "Family activity",
  ])
    expect(dialog.textContent).not.toContain(text);
});
it("matches loaded family locally while public data is unavailable, without caching another user's rows", async () => {
  api.mockRejectedValue(new ApiError("Clash unavailable", 503));
  await mount();
  await act(async () => input("fixture"));
  await act(async () => vi.advanceTimersByTime(350));
  expect(host.textContent).toContain("Family fixture");
  await act(async () =>
    root.render(
      <GameSearch
        key="second-user"
        session={{
          ...session,
          user: { id: "another", username: "Second fixture" },
        }}
        accounts={[]}
        onTasks={vi.fn()}
        query="fixture"
        onQuery={vi.fn()}
      />,
    ),
  );
  expect(host.textContent).not.toContain("Family fixture");
});

it("opens authorized family details from loaded data without public detail reads", async () => {
  api.mockResolvedValue({ results: [] });
  await mount();
  await act(async () => input("Family fixture"));
  await act(async () => vi.advanceTimersByTime(350));
  await act(async () =>
    host.querySelector<HTMLButtonElement>(".search-result button")!.click(),
  );
  const dialog = document.querySelector("dialog")!;
  expect(dialog.textContent).toContain("Linked player");
  expect(dialog.textContent).toContain("Family activity");
  expect(
    api.mock.calls.filter(([path]) =>
      String(path).startsWith("/search/details"),
    ),
  ).toHaveLength(0);
});
