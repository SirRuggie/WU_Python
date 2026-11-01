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
  expect(host.textContent).toContain("0 of 1 in clan");
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
