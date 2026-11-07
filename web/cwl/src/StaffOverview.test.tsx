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
