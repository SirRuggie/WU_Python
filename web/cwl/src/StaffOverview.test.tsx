// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import { api } from "./api";
import StaffOverview from "./StaffOverview";

vi.mock("./api", () => ({
  api: vi.fn(),
  ApiError: class extends Error {},
}));
vi.mock("./DashboardIcon", () => ({
  default: ({ name }: { name: string }) => <span data-icon={name} />,
}));

it("uses menu icons and labels for roster and ticket destinations", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.mocked(api).mockResolvedValue({
    checked_at: 1,
    seasons: [],
    tickets: { open: 2, url: null },
    failures_count: 0,
    failures: [],
    warnings: [],
    areas: ["roster", "applications-settings"],
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<StaffOverview onNavigate={vi.fn()} />));
    expect(
      [...host.querySelectorAll("h2")].map((heading) => heading.textContent),
    ).toEqual([
      " CWL placement",
      " Tickets",
      " Recent failed actions",
      "Your tools",
    ]);
    expect(
      [...host.querySelectorAll("h2 [data-icon]")].map((icon) =>
        icon.getAttribute("data-icon"),
      ),
    ).toEqual(["roster", "ticket", "warning"]);
    expect(
      host.querySelector(".staff-overview-shortcuts")?.textContent,
    ).toContain("Build roster →");
    expect(
      host.querySelector(".staff-overview-shortcuts")?.textContent,
    ).toContain("Ticket settings →");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("styles the external ticket console link as a secondary button", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.mocked(api).mockResolvedValue({
    checked_at: 1,
    seasons: [],
    tickets: { open: 2, url: "https://tickets.example.test/" },
    failures_count: 0,
    failures: [],
    warnings: [],
    areas: [],
  });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<StaffOverview onNavigate={vi.fn()} />));
    const link = host.querySelector<HTMLAnchorElement>(
      'a[href="https://tickets.example.test/"]',
    )!;
    expect(link.className).toBe("button");
    expect(link.target).toBe("_blank");
    expect(link.rel).toBe("noreferrer");
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("marks only the pending refresh and blocks a second native click", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const snapshot = {
    checked_at: 1,
    seasons: [],
    tickets: null,
    failures_count: 0,
    failures: [],
    warnings: [],
    areas: [],
  };
  let finish!: (value: typeof snapshot) => void;
  vi.mocked(api).mockImplementation((path) =>
    path === "/manage/staff-overview"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve({}),
  );
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  try {
    await act(async () => root.render(<StaffOverview onNavigate={vi.fn()} />));
    const refresh = host.querySelector<HTMLButtonElement>(".page-head button")!;
    expect(refresh.textContent?.trim()).toBe("Refreshing…");
    expect(refresh.disabled).toBe(true);
    expect(refresh.getAttribute("aria-busy")).toBe("true");
    const calls = () =>
      vi
        .mocked(api)
        .mock.calls.filter(([path]) => path === "/manage/staff-overview")
        .length;
    const initialCalls = calls();
    await act(async () => {
      refresh.click();
      refresh.click();
    });
    expect(calls()).toBe(initialCalls);
    await act(async () => finish(snapshot));
    expect(refresh.textContent?.trim()).toBe("Refresh");
    expect(refresh.disabled).toBe(false);
    expect(refresh.hasAttribute("aria-busy")).toBe(false);
    await act(async () => refresh.click());
    expect(calls()).toBe(initialCalls + 1);
    expect(refresh.getAttribute("aria-busy")).toBe("true");
    await act(async () => {
      refresh.click();
      refresh.click();
    });
    expect(calls()).toBe(initialCalls + 1);
    await act(async () => finish(snapshot));
    expect(refresh.hasAttribute("aria-busy")).toBe(false);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});

it("joins exact summary rows to App metadata by id without fetching again or changing counts/destinations", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const summary = {
    checked_at: 1,
    seasons: [
      { id: 1, label: "2026-08", signed_up: 12, unplaced: 3 },
      { id: 2, label: "Bound staff archive", signed_up: 2, unplaced: 1 },
      { id: 9, label: "2026-09", signed_up: 5, unplaced: 0 },
      { id: 10, label: "Unbound notes", signed_up: 1, unplaced: 1 },
    ],
    tickets: null,
    failures_count: 0,
    failures: [],
    warnings: [],
    areas: ["roster"],
  };
  vi.mocked(api).mockReset().mockResolvedValue(summary);
  const metadata = [
    {
      id: 2,
      label: "Bound staff archive",
      cwl_month: "2026-10",
      status: "archived",
      signup_open: false,
    },
    {
      id: 1,
      label: "2026-08",
      cwl_month: "2026-11",
      status: "draft",
      signup_open: true,
    },
  ];
  const onNavigate = vi.fn(),
    host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const labels = () =>
    [...host.querySelectorAll(".staff-overview-row strong")].map(
      (row) => row.textContent,
    );
  const counts = () =>
    [...host.querySelectorAll(".staff-overview-row p")].map(
      (row) => row.textContent,
    );
  try {
    await act(async () =>
      root.render(<StaffOverview onNavigate={onNavigate} />),
    );
    expect(labels()).toEqual([
      "August 2026",
      "Bound staff archive",
      "September 2026",
      "Unbound notes",
    ]);
    const beforeCounts = counts(),
      reads = vi.mocked(api).mock.calls.length;
    await act(async () =>
      root.render(<StaffOverview seasons={metadata} onNavigate={onNavigate} />),
    );
    expect(labels()).toEqual([
      "November 2026",
      "October 2026",
      "September 2026",
      "Unbound notes",
    ]);
    expect(counts()).toEqual(beforeCounts);
    expect(vi.mocked(api).mock.calls).toHaveLength(reads);
    expect(summary.seasons.every((row) => !("cwl_month" in row))).toBe(true);
    for (const button of host.querySelectorAll<HTMLButtonElement>(
      ".staff-overview-row button",
    ))
      await act(async () => button.click());
    expect(onNavigate.mock.calls).toEqual([
      ["roster", "1"],
      ["roster", "2"],
      ["roster", "9"],
      ["roster", "10"],
    ]);
    expect(
      vi.mocked(api).mock.calls.every((call) => call[1] === undefined),
    ).toBe(true);
  } finally {
    await act(async () => root.unmount());
    host.remove();
  }
});
