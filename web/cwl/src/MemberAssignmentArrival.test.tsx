// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api } from "./api";
import MemberAssignments from "./MemberAssignments";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("shows only confirmed checks and per-clan counts across multiple clans", async () => {
  const accounts = ["arrived", "missing", "unknown", undefined, "arrived"].map(
    (arrival_status, index) => ({
      tag: `#P${index}`,
      player_name: `Player ${index}`,
      pool: "main",
      town_hall: 17,
      assigned_clan_tag: index === 4 ? "#OTHER" : "#HOST",
      assigned_clan_name: index === 4 ? "Other host" : "Host",
      arrival_status,
      current_clan_tag:
        arrival_status === "arrived"
          ? index === 4
            ? "#OTHER"
            : "#HOST"
          : null,
      current_clan_name: null,
      current_clan_checked_at: ["arrived", "missing"].includes(
        arrival_status || "",
      )
        ? new Date().toISOString()
        : undefined,
    }),
  );
  vi.mocked(api).mockResolvedValue({
    published: {
      version: 1,
      published_at: "2026-11-01",
      joining_instructions: "",
    },
    accounts,
  });
  await act(async () =>
    root.render(<MemberAssignments seasonId="1" seasons={[]} />),
  );
  expect(
    host.querySelectorAll('[role="img"][aria-label="In clan"]'),
  ).toHaveLength(2);
  expect(host.textContent).toContain("1 of 4 in clan");
  expect(host.textContent).toContain("All 1 in clan");
  expect(host.querySelectorAll(".member-clan-row")).toHaveLength(5);
  expect(vi.mocked(api)).toHaveBeenCalledTimes(1);
});
it("renders unavailable location accounts without a false check", async () => {
  vi.mocked(api).mockResolvedValue({
    published: {
      version: 1,
      published_at: "2026-11-01",
      joining_instructions: "",
    },
    accounts: [
      {
        tag: "#P",
        player_name: "Unknown",
        pool: "main",
        town_hall: 17,
        assigned_clan_tag: "#HOST",
        assigned_clan_name: "Host",
      },
    ],
  });
  await act(async () =>
    root.render(<MemberAssignments seasonId="1" seasons={[]} />),
  );
  expect(host.querySelector('[aria-label="In clan"]')).toBeNull();
  expect(host.textContent).not.toContain("0 of 1 in clan");
  expect(host.querySelector(".member-clan-head small")?.textContent).toContain(
    "1 account",
  );
  expect(host.textContent).toContain("Unknown");
});
it("updates checks through the existing refresh without adding row requests", async () => {
  vi.useFakeTimers();
  const response = (arrival_status: string) => ({
    published: {
      version: 1,
      published_at: "2026-11-01",
      joining_instructions: "",
    },
    accounts: [
      {
        tag: "#P",
        player_name: "Waiting",
        pool: "main",
        town_hall: 17,
        assigned_clan_tag: "#HOST",
        assigned_clan_name: "Host",
        arrival_status,
        current_clan_tag: arrival_status === "arrived" ? "#HOST" : null,
        current_clan_name: null,
        current_clan_checked_at:
          arrival_status === "unknown" ? undefined : new Date().toISOString(),
      },
    ],
  });
  vi.mocked(api)
    .mockResolvedValueOnce(response("unknown"))
    .mockResolvedValue(response("arrived"));
  try {
    await act(async () =>
      root.render(<MemberAssignments seasonId="1" seasons={[]} />),
    );
    expect(host.querySelector('[aria-label="In clan"]')).toBeNull();
    expect(api).toHaveBeenCalledTimes(1);
    await act(async () => vi.advanceTimersByTime(30000));
    expect(host.querySelector('[aria-label="In clan"]')).not.toBeNull();
    expect(api).toHaveBeenCalledTimes(2);
  } finally {
    vi.useRealTimers();
  }
});
it("keeps verified checks across cache expiry and clears them only after a newer confirmed move", async () => {
  vi.useFakeTimers();
  const start = Date.now();
  const result = (
    tag: string | null,
    checked?: string,
    status = "current",
  ) => ({
    published: {
      version: 1,
      published_at: "2026-11-01",
      joining_instructions: "",
    },
    accounts: [
      {
        tag: "#P",
        player_name: "Player",
        pool: "main",
        town_hall: 17,
        assigned_clan_tag: "#HOST",
        assigned_clan_name: "Host",
        current_clan_tag: tag,
        current_clan_name: null,
        current_clan_checked_at: checked,
        current_clan_status: status,
        arrival_status: status === "current" ? "arrived" : "unknown",
      },
    ],
  });
  vi.mocked(api).mockResolvedValue(
    result("#HOST", new Date(start).toISOString()),
  );
  try {
    await act(async () =>
      root.render(<MemberAssignments seasonId="1" seasons={[]} />),
    );
    expect(host.textContent).toContain("All 1 in clan");
    vi.mocked(api).mockResolvedValue(
      result("#HOST", new Date(start).toISOString(), "stale"),
    );
    await act(async () => vi.advanceTimersByTime(150000));
    expect(host.querySelector('[aria-label="In clan"]')).not.toBeNull();
    expect(host.textContent).toContain("All 1 in clan");
    vi.mocked(api).mockResolvedValue(result(null, undefined, "unavailable"));
    await act(async () => vi.advanceTimersByTime(30000));
    expect(host.textContent).toContain("All 1 in clan");
    vi.mocked(api).mockResolvedValue(
      result("#ELSE", new Date(start + 180001).toISOString()),
    );
    await act(async () => vi.advanceTimersByTime(30000));
    expect(host.querySelector('[aria-label="In clan"]')).toBeNull();
    expect(host.textContent).toContain("0 of 1 in clan");
  } finally {
    vi.useRealTimers();
  }
});
it("does not carry another season's verified location into a cold unknown view", async () => {
  vi.mocked(api).mockResolvedValue({
    published: { version: 1, published_at: "2026-11-01" },
    accounts: [
      {
        tag: "#P",
        player_name: "Player",
        pool: "main",
        town_hall: 17,
        assigned_clan_tag: "#HOST",
        assigned_clan_name: "Host",
        current_clan_tag: "#HOST",
        current_clan_name: null,
        current_clan_checked_at: new Date().toISOString(),
      },
    ],
  });
  await act(async () =>
    root.render(<MemberAssignments seasonId="1" seasons={[]} />),
  );
  expect(host.querySelector('[aria-label="In clan"]')).not.toBeNull();
  vi.mocked(api).mockResolvedValue({
    published: { version: 1, published_at: "2026-11-01" },
    accounts: [
      {
        tag: "#P",
        player_name: "Player",
        pool: "main",
        town_hall: 17,
        assigned_clan_tag: "#HOST",
        assigned_clan_name: "Host",
      },
    ],
  });
  await act(async () =>
    root.render(<MemberAssignments seasonId="2" seasons={[]} />),
  );
  expect(host.querySelector('[aria-label="In clan"]')).toBeNull();
  expect(host.querySelector(".member-clan-head small")?.textContent).toBe(
    "#HOST · 1 account",
  );
});
it("shows eleven unknown accounts before displaying a partial verified in-clan count", async () => {
  const accounts = Array.from({ length: 11 }, (_, index) => ({
    tag: `#P${index}`,
    player_name: `Player ${index}`,
    pool: "main",
    town_hall: 17,
    assigned_clan_tag: "#HOST",
    assigned_clan_name: "Host",
  }));
  const published = {
    version: 1,
    published_at: "2026-11-01",
    joining_instructions: "",
  };
  vi.mocked(api).mockResolvedValue({ published, accounts });
  await act(async () =>
    root.render(<MemberAssignments seasonId="1" seasons={[]} />),
  );
  expect(host.querySelector(".member-clan-head small")?.textContent).toBe(
    "#HOST · 11 accounts",
  );
  vi.mocked(api).mockResolvedValue({
    published,
    accounts: accounts.map((a, index) =>
      index < 8
        ? {
            ...a,
            current_clan_tag: "#HOST",
            current_clan_name: "Host",
            current_clan_checked_at: new Date().toISOString(),
          }
        : a,
    ),
  });
  await act(async () =>
    [...host.querySelectorAll<HTMLButtonElement>("button")]
      .find((b) => b.textContent === "Refresh")!
      .click(),
  );
  expect(host.querySelector(".member-clan-head small")?.textContent).toBe(
    "#HOST · 8 of 11 in clan",
  );
});
