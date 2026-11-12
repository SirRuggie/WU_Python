// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ExportWorkspace from "./ExportWorkspace";
import { ApiError } from "./api";

const { api, fetchExcel, access } = vi.hoisted(() => ({
  api: vi.fn(),
  fetchExcel: vi.fn(),
  access: { bonuses: true, send: true },
}));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: (name: string) =>
    name === "cwl_bonuses" ? access.bonuses : access.send,
}));
vi.mock("./readRetry", () => ({ fetchReadWithRetry: fetchExcel }));
const seasons = [
  { id: 1, label: "2026-11", status: "draft", signup_open: true },
  { id: 2, label: "October 2026", status: "archived", signup_open: false },
];
const sample = (
  kind = "accounts",
  basis = "current",
  count = 1,
  published = true,
) => ({
  kind,
  basis,
  summary: {
    season_label: "November 2026",
    season_status: "draft",
    cwl_month: "2026-11",
    published_version: published ? 6 : null,
    published_at: "2026-11-01T12:00:00Z",
    published_available: published,
  },
  columns: ["player_name", "effective_weight", "cycle"],
  rows: count
    ? [
        {
          player_name: "<script> @everyone",
          tag: "#P2Y",
          pool: "main",
          assigned_clan_name: "Long fixture hosting clan",
          effective_weight: 179000,
          cycle: "2026-11",
          participation_matches_roster: false,
          matches_roster: false,
          attacks: 2,
          stars: 5,
        },
      ]
    : [],
  counts: { rows: count },
});
let host: HTMLDivElement;
let root: Root;
const settle = async () => {
  await act(async () => {
    await new Promise((r) => setTimeout(r, 0));
  });
};
const render = async (season = "1", onSeasonChange = vi.fn()) => {
  await act(async () =>
    root.render(
      <ExportWorkspace
        seasonId={season}
        seasons={seasons}
        onSeasonChange={onSeasonChange}
      />,
    ),
  );
  await settle();
};
const select = (label: string) =>
  [...host.querySelectorAll("label")]
    .find((x) => x.textContent?.trim().startsWith(label))!
    .querySelector("select")!;
const change = async (label: string, value: string) => {
  if (label === "Roster version") {
    await act(async () =>
      button(value === "current" ? "Working" : "Published").click(),
    );
    await settle();
    return;
  }
  await act(async () => {
    const input = select(label);
    input.value = value;
    input.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await settle();
};
const button = (label: string) =>
  [...host.querySelectorAll("button")].find((x) => x.textContent === label)!;

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset();
  access.bonuses = true;
  access.send = true;
  fetchExcel.mockReset();
  api.mockImplementation(async (path: string) => {
    const q = new URLSearchParams(path.split("?")[1]);
    return sample(q.get("kind")!, q.get("basis")!);
  });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  class FixtureURL extends URL {}
  FixtureURL.createObjectURL = vi.fn(() => "blob:fixture");
  FixtureURL.revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", FixtureURL);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("uses the four plain dataset names and formats only preview values", async () => {
  await render();
  expect(host.querySelector("h1")?.textContent).toBe("Exports & history");
  expect([...select("Show").options].map((x) => x.text)).toEqual([
    "Roster",
    "Signups",
    "Results history",
    "Bonus winners",
  ]);
  expect(host.querySelector(".roster-menu-current")?.textContent).toBe(
    "November 2026",
  );
  expect(host.textContent).toContain("179k");
  expect(host.textContent).toContain("November 2026");
  expect(host.textContent).not.toContain("Some results are blank");
  await change("Show", "participation");
  expect(host.textContent).toContain(
    "Some results are blank (different clan). See Results history.",
  );
  expect(host.textContent).toContain("<script> @everyone");
  expect(host.querySelector("script")).toBeNull();
  expect(host.textContent).not.toContain("placements and weights are frozen");
  expect(host.textContent).not.toContain("Saved working placements use");
});

it("defaults Published and keeps working rows hidden until a requested published read completes", async () => {
  await render();
  expect(button("Published").getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).not.toContain("Roster version");
  let finish: (value: unknown) => void = () => {};
  api.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await change("Roster version", "current");
  expect(host.querySelector(".export-record")).toBeNull();
  await act(async () => finish(sample()));
  expect(api).toHaveBeenLastCalledWith(
    "/seasons/1/export-preview?kind=accounts&basis=current",
  );
});

it("explains disabled publication and permits an empty workbook", async () => {
  api.mockResolvedValue(sample("accounts", "current", 0, false));
  await render();
  expect(button("Published").disabled).toBe(true);
  expect(button("Working").getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).toContain("Not published yet");
  expect(button("Download season (Excel)").disabled).toBe(false);
});

it("renders all grouped accounts without search or paging", async () => {
  const data = sample();
  data.rows = Array.from({ length: 26 }, (_, i) => ({
    ...data.rows[0],
    tag: `#P${i}`,
  }));
  data.counts.rows = 26;
  api.mockResolvedValue(data);
  await render();
  expect(host.querySelectorAll(".export-record")).toHaveLength(26);
  expect(host.querySelector('input[type="search"]')).toBeNull();
  expect(
    host.querySelector('nav[aria-label="Export preview pages"]'),
  ).toBeNull();
  expect(button("Download season (Excel)").disabled).toBe(false);
});

it("downloads the season workbook using the selected Published or Working basis", async () => {
  const file = new Blob(["xlsx fixture"]);
  fetchExcel.mockResolvedValue({
    ok: true,
    headers: {
      get: (key: string) =>
        key === "content-type"
          ? "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
          : null,
    },
    blob: async () => file,
  });
  await render();
  for (const basis of ["current", "published"]) {
    await change("Roster version", basis);
    await act(async () => button("Download season (Excel)").click());
    expect(fetchExcel).toHaveBeenLastCalledWith(
      `/api/cwl/seasons/1/export.xlsx?basis=${basis}`,
      expect.objectContaining({
        credentials: "same-origin",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(URL.createObjectURL).toHaveBeenLastCalledWith(file);
  }
});

it("offers one download retry after failure and blocks duplicate pending requests", async () => {
  let finish: (value: unknown) => void = () => {};
  fetchExcel.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await render();
  await act(async () => {
    button("Download season (Excel)").click();
    button("Download season (Excel)").click();
  });
  expect(fetchExcel).toHaveBeenCalledTimes(1);
  await act(async () =>
    finish({
      ok: false,
      status: 500,
      json: async () => ({ error: "Private server detail" }),
    }),
  );
  await settle();
  expect(host.textContent).toContain("Download failed.");
  expect(host.textContent).not.toContain("Private server detail");
  fetchExcel.mockResolvedValue({
    ok: true,
    headers: {
      get: () =>
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    },
    blob: async () => new Blob(["179000"]),
  });
  await act(async () => button("Retry download").click());
  await settle();
  expect(fetchExcel).toHaveBeenCalledTimes(2);
});

it.each([401, 403])(
  "hides Retry and clears protected preview after denied download %i",
  async (status) => {
    fetchExcel.mockResolvedValue({
      ok: false,
      status,
      json: async () => ({ error: "Denied" }),
    });
    const changed = vi.spyOn(window, "dispatchEvent");
    await render();
    await act(async () => button("Download season (Excel)").click());
    await settle();
    expect(host.textContent).toContain(
      "You do not have access to this download.",
    );
    expect(button("Retry")).toBeUndefined();
    expect(host.querySelector(".export-record")).toBeNull();
    expect(changed).toHaveBeenCalledWith(
      expect.objectContaining({ type: "dashboard-access-changed" }),
    );
  },
);

it.each([401, 403])("hides Retry for denied preview %i", async (status) => {
  api.mockRejectedValue(new ApiError("Private denial", status));
  await render();
  expect(button("Retry")).toBeUndefined();
  expect(host.textContent).toContain("You do not have access to this export.");
});

it("ignores stale previews across a season change", async () => {
  let finish: (value: unknown) => void = () => {};
  api.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await render();
  await render("2");
  expect(api).toHaveBeenLastCalledWith(
    "/seasons/2/export-preview?kind=accounts&basis=published",
  );
  await act(async () =>
    finish({ ...sample(), rows: [{ player_name: "Stale private row" }] }),
  );
  await settle();
  expect(host.textContent).not.toContain("Stale private row");
  expect(host.textContent).toContain("<script> @everyone");
});

it("drops a late published response after changing the season", async () => {
  let finish: (value: unknown) => void = () => {};
  api.mockImplementation((path: string) =>
    path === "/seasons/1/export-preview?kind=accounts&basis=published"
      ? new Promise((resolve) => {
          finish = resolve;
        })
      : Promise.resolve(sample()),
  );
  await render();
  expect(host.querySelector(".export-record")).toBeNull();
  await render("2");
  expect(host.querySelector(".export-record")).not.toBeNull();
  await act(async () =>
    finish({ ...sample(), rows: [{ player_name: "Old publication" }] }),
  );
  expect(host.textContent).not.toContain("Old publication");
});

it("aborts an in-flight Excel when changing season and does not offer its stale Blob", async () => {
  let finish: (value: unknown) => void = () => {};
  fetchExcel.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await render();
  await act(async () => button("Download season (Excel)").click());
  const signal = fetchExcel.mock.calls[0][1].signal as AbortSignal;
  await render("2");
  expect(signal.aborted).toBe(true);
  await act(async () =>
    finish({
      ok: true,
      headers: {
        get: () =>
          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
      },
      blob: async () => new Blob(["old"]),
    }),
  );
  expect(URL.createObjectURL).not.toHaveBeenCalled();
});

it.each([
  { published: true, mode: "Published" },
  { published: true, mode: "Working" },
  { published: false, mode: "Working" },
])(
  "reactivating selected $mode (published=$published) preserves records without a read",
  async ({ published, mode }) => {
    api.mockResolvedValue(sample("accounts", "current", 1, published));
    await render();
    if (published && mode === "Working") {
      await act(async () => button("Working").click());
      await settle();
    }
    expect(button(mode).getAttribute("aria-pressed")).toBe("true");
    const before = api.mock.calls.length;
    const records = host.querySelector(".export-record")?.textContent;
    await act(async () => button(mode).click());
    await settle();
    expect(host.querySelector(".export-record")?.textContent).toBe(records);
    expect(api).toHaveBeenCalledTimes(before);
  },
);

it.each([
  { bonuses: false, send: false, visible: false },
  { bonuses: true, send: false, visible: true },
  { bonuses: false, send: true, visible: true },
])(
  "gates workbook controls while keeping nonwinner previews: $bonuses/$send",
  async ({ bonuses, send, visible }) => {
    Object.assign(access, { bonuses, send });
    await render();
    expect(Boolean(button("Download season (Excel)"))).toBe(visible);
    expect(
      [...select("Show").options].some((row) => row.value === "bonus-history"),
    ).toBe(visible);
    expect(host.querySelector(".export-record")).not.toBeNull();
    expect(
      api.mock.calls.every(
        (call) => !String(call[0]).includes("kind=bonus-history"),
      ),
    ).toBe(true);
  },
);
