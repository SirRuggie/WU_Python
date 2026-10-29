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
