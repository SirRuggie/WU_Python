// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const { api, grants } = vi.hoisted(() => ({
  api: vi.fn(),
  grants: new Set<string>(),
}));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: (key: string) => grants.has(key),
}));
import ExportWorkspace from "./ExportWorkspace";
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
const seasons = [
  { id: 1, label: "2026-11", status: "draft", signup_open: true },
  { id: 2, label: "2026-08", status: "archived", signup_open: false },
];
const payload = (published = true, status = "draft") => ({
  summary: {
    season_label: "2026-11",
    season_status: status,
    published_available: published,
    published_version: published ? 1 : null,
    published_at: null,
    cwl_month: "2026-11",
  },
  rows: [
    {
      tag: "#P2Y",
      pool: "lazy",
      player_name: "Fixture",
      assigned_clan_name: "Lazy",
      clan_name: "Lazy",
      source: "import",
    },
  ],
  counts: { rows: 1 },
});
const render = (sid = "1") =>
  act(async () =>
    root.render(
      <ExportWorkspace
        seasonId={sid}
        seasons={seasons}
        onSeasonChange={() => {}}
      />,
    ),
  );
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  grants.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  api.mockReset().mockResolvedValue(payload());
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it.each(["cwl_bonuses", "cwl_send", ""])(
  "Bonus winners follows the existing OR grant: %s",
  async (grant) => {
    if (grant) grants.add(grant);
    await render();
    const show = host.querySelector("select")!;
    expect(
      [...show.options].some((option) => option.value === "bonus-history"),
    ).toBe(Boolean(grant));
    expect(host.querySelector(".participation-history")).toBeNull();
    expect(host.querySelector(".bonus-history")).toBeNull();
    expect(
      api.mock.calls.every((call) =>
        String(call[0]).includes("export-preview"),
      ),
    ).toBe(true);
    if (grant) {
      await act(async () => {
        show.value = "bonus-history";
        show.dispatchEvent(new Event("change", { bubbles: true }));
      });
      expect(host.textContent).toContain("Imported");
    }
    expect(api.mock.calls.every((call) => !call[1] || call[1] === "GET")).toBe(
      true,
    );
  },
);
it("archived months have no switch and no working fallback when unpublished", async () => {
  api.mockResolvedValue(payload(false, "archived"));
  await render("2");
  expect(host.querySelector('[aria-label="Roster basis"]')).toBeNull();
  expect(host.textContent).toContain("No roster saved for this month.");
  expect(host.textContent).not.toContain("Fixture");
});
it("clears winner data when the grant is revoked", async () => {
  grants.add("cwl_send");
  await render();
  const show = host.querySelector("select")!;
  await act(async () => {
    show.value = "bonus-history";
    show.dispatchEvent(new Event("change", { bubbles: true }));
  });
  expect(host.textContent).toContain("Imported");
  grants.clear();
  await render();
  expect(host.textContent).not.toContain("Imported");
  expect(host.textContent).toContain("You do not have access");
});
it("orders month-name seasons newest first without archive suffix", async () => {
  const { monthSeasons } = await import("./exportHistory");
  expect(
    monthSeasons([
      { ...seasons[1] },
      { ...seasons[0] },
      { id: 3, label: "October 2026", status: "archived", signup_open: false },
    ]).map((s) => s.id),
  ).toEqual([1, 2, 3]);
  await render();
  expect(host.textContent).not.toContain("· Archived");
});

it("uses the bound month before a free label, ISO fallback, then untouched free labels last", async () => {
  const { monthSeasons, seasonMonthLabel } = await import("./exportHistory");
  const rows = [
    {
      id: 1,
      label: "September staff history",
      cwl_month: "2026-09",
      status: "archived",
      signup_open: false,
    },
    {
      id: 2,
      label: "2026-08",
      cwl_month: null,
      status: "archived",
      signup_open: false,
    },
    {
      id: 9,
      label: "Unbound newest",
      cwl_month: null,
      status: "draft",
      signup_open: false,
    },
    {
      id: 3,
      label: "Unbound older",
      cwl_month: null,
      status: "draft",
      signup_open: false,
    },
  ];
  expect(monthSeasons(rows).map((row) => row.id)).toEqual([1, 2, 9, 3]);
  expect(rows.map((row) => seasonMonthLabel(row))).toEqual([
    "September 2026",
    "August 2026",
    "Unbound newest",
    "Unbound older",
  ]);
  await act(async () =>
    root.render(
      <ExportWorkspace seasonId="1" seasons={rows} onSeasonChange={() => {}} />,
    ),
  );
  expect(host.querySelector(".roster-menu-current")?.textContent).toBe(
    "September 2026",
  );
});
