// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const state = vi.hoisted(() => ({ value: null as any }));
vi.mock("./useDeclarationData", () => ({ default: () => state.value }));
import ArrivalCheck from "./ArrivalCheck";
import { staffDetailsEvent } from "./staffDetailsRequest";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
const now = Date.now();
function makeData() {
  const accounts = Array.from({ length: 33 }, (_, i) => ({
    tag: `#P000${i}`,
    player_name: `Player ${i}`,
    town_hall: 18,
    pool: "main",
    hosting_pool: "main",
    assigned_clan_tag: i < 16 ? "#A" : "#B",
    assigned_clan_name: i < 16 ? "Amber" : "Blaze",
    user_id: i === 0 ? "" : "505227988229554179",
    current_clan_tag: i === 0 ? "#ELSE" : i < 16 ? "#A" : "#B",
    current_clan_name: i === 0 ? "Elsewhere" : i < 16 ? "Amber" : "Blaze",
    current_clan_checked_at: new Date(now).toISOString(),
    outside_family: i === 0,
  }));
  return {
    arrival: {
      source: "published",
      publication_available: true,
      publication_outdated: false,
      version: 1,
      accounts,
    },
    roster: {
      revision: 1,
      accounts: [],
      clans: [
        { tag: "#A", capacity: 15 },
        { tag: "#B", capacity: 30 },
      ],
    },
    publication: { published: { version: 1 }, last_publication: null },
  };
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  localStorage.clear();
  vi.spyOn(window, "matchMedia").mockImplementation(
    () =>
      ({
        matches: true,
        addEventListener() {},
        removeEventListener() {},
      }) as any,
  );
  Element.prototype.scrollIntoView = vi.fn();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  const data = makeData();
  state.value = {
    data,
    records: Object.fromEntries(data.arrival.accounts.map((a) => [a.tag, a])),
    now,
    checkedAt: now,
    refresh: vi.fn(),
    error: "",
    checking: false,
  };
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});
const render = async () =>
  act(async () => root.render(<ArrivalCheck seasonId="1" />));
const toggles = () => [
  ...host.querySelectorAll<HTMLButtonElement>(".declaration-clan-toggle"),
];
it("starts collapsed, counts overfilled ready clans, opens one phone clan and preserves late players", async () => {
  await render();
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(0);
  expect(host.textContent).toContain("1 / 2 clans ready to declare");
  await act(async () => toggles()[0].click());
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(16);
  expect(host.querySelector(".declaration-player")?.className).toContain(
    "missing",
  );
  expect(host.querySelector(".declaration-copy")).toBeNull();
  await act(async () => toggles()[1].click());
  expect(toggles()[0].getAttribute("aria-expanded")).toBe("false");
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(17);
});
it("desktop permits multiple open clans; search opens and highlights a match", async () => {
  vi.mocked(window.matchMedia).mockReturnValue({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
  } as any);
  await render();
  await act(async () => {
    toggles()[0].click();
    toggles()[1].click();
  });
  expect(host.querySelectorAll(".declaration-player")).toHaveLength(33);
  const input = host.querySelector<HTMLInputElement>('input[type="search"]')!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, "Player 20");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  expect(host.querySelector(".is-match")?.textContent).toContain("Player 20");
});
it.each(["hidden", "never"])(
  "%s has no player list and links to Finalize",
  async (kind) => {
    state.value.data.publication.published = null;
    state.value.data.arrival.publication_available = false;
    if (kind === "hidden")
      state.value.data.publication.last_publication = {
        version: 2,
        published_at: new Date(now).toISOString(),
        withdrawn_at: new Date(now).toISOString(),
      };
    await render();
    expect(host.textContent).toContain(
      kind === "hidden"
        ? "Hidden from members · last published version 2"
        : "Publish the roster first",
    );
    expect(host.querySelectorAll(".declaration-clan")).toHaveLength(0);
    expect(host.querySelector("a")?.getAttribute("href")).toContain(
      "step=review",
    );
  },
);
it("draft changed remains ready; names open read-only snapshot Details with clan order", async () => {
  state.value.data.arrival.publication_outdated = true;
  const open = vi.fn();
  window.addEventListener(staffDetailsEvent, open);
  await render();
  await act(async () => toggles()[0].click());
  const name = host.querySelector<HTMLButtonElement>(".roster-player-name")!;
  await act(async () => name.click());
  const request = (open.mock.calls[0][0] as CustomEvent).detail;
  expect(request.viewOnly).toBe("declaration");
  expect(request.publishedSnapshot.version).toBe(1);
  expect(request.order).toHaveLength(16);
  expect(host.textContent).toContain("1 / 2 clans ready");
  expect(
    [...host.querySelectorAll("button")].some(
      (b) => b.textContent === "Details",
    ),
  ).toBe(false);
  window.removeEventListener(staffDetailsEvent, open);
});
it("no result is red, no clan is never Outside family, and no weight or action menu is rendered", async () => {
  const accounts = state.value.data.arrival.accounts;
  delete state.value.records[accounts[0].tag];
  state.value.records[accounts[1].tag] = {
    current_clan_tag: null,
    current_clan_name: null,
    current_clan_checked_at: new Date(now).toISOString(),
    outside_family: true,
  };
  await render();
  await act(async () => toggles()[0].click());
  expect(host.querySelectorAll(".compare-account-missing")).toHaveLength(2);
  expect(host.textContent).toContain("Checking…");
  expect(host.textContent).not.toContain("Outside family");
  expect(host.textContent).not.toContain("No weight");
  expect(host.querySelector('[aria-label^="Actions for"]')).toBeNull();
  expect(
    host.querySelectorAll(".compare-account-arrived .discord-contact"),
  ).toHaveLength(0);
});
it("Copy mentions deduplicates, lists unlinked players and falls back to selectable text", async () => {
  const a = state.value.data.arrival.accounts;
  for (const row of a)
    state.value.records[row.tag] = { ...row, current_clan_tag: "#ELSE" };
  Object.defineProperty(navigator, "clipboard", {
    configurable: true,
    value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
  });
  await render();
  await act(async () => toggles()[0].click());
  const copy = [...host.querySelectorAll<HTMLButtonElement>("button")].find(
    (b) => b.textContent === "Copy mentions",
  )!;
  expect(host.textContent).toContain("Can't mention: Player 0");
  await act(async () => copy.click());
  expect(host.querySelector("textarea")?.value).toBe("<@505227988229554179>");
  vi.mocked(navigator.clipboard.writeText).mockResolvedValue();
  await act(async () => copy.click());
  expect(host.textContent).toContain("Copied 1 mentions");
});
it("keeps the draft-changed notice muted without blocking readiness", async () => {
  state.value.data.arrival.publication_outdated = true;
  await render();
  expect(host.querySelector(".declaration-help")?.textContent).toBe(
    "Checking published version 1 · the draft has changes members can't see yet",
  );
  expect(host.textContent).toContain("1 / 2 clans ready to declare");
});
it("excludes awaiting placement from late totals and gives it a neutral section", async () => {
  state.value.data.arrival.accounts[0].assigned_clan_tag = null;
  state.value.data.arrival.accounts[0].assigned_clan_name = null;
  await render();
  expect(host.querySelector(".declaration-summary")?.textContent).toContain(
    "0 players not in their clan",
  );
  expect(host.querySelector(".is-unassigned")?.textContent).toContain(
    "Awaiting placement",
  );
  expect(host.querySelector(".is-unassigned")?.className).not.toContain(
    "is-not-ready",
  );
});
it("keeps readiness help collapsed until explicitly opened", async () => {
  await render();
  expect(host.textContent).not.toContain("Ready = enough");
  await act(async () =>
    host
      .querySelector<HTMLButtonElement>('[aria-label="About readiness"]')!
      .click(),
  );
  expect(host.textContent).toContain("Ready = enough");
});
