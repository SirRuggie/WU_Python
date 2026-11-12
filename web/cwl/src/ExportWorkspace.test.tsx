// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import ExportWorkspace from "./ExportWorkspace";
import { ApiError } from "./api";

const { api, fetchCsv } = vi.hoisted(() => ({
  api: vi.fn(),
  fetchCsv: vi.fn(),
}));
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
vi.mock("./DashboardPermissions", () => ({
  useDashboardPermission: () => true,
}));
vi.mock("./readRetry", () => ({ fetchReadWithRetry: fetchCsv }));
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
  fetchCsv.mockReset();
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

it("explains disabled publication and prevents downloading zero rows", async () => {
  api.mockResolvedValue(sample("accounts", "current", 0, false));
  await render();
  expect(button("Published").disabled).toBe(true);
  expect(button("Working").getAttribute("aria-pressed")).toBe("true");
  expect(host.textContent).toContain("Not published yet");
  expect(button("Download CSV").disabled).toBe(true);
  await act(async () => button("Download CSV").click());
  expect(fetchCsv).not.toHaveBeenCalled();
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
  expect(button("Download CSV").disabled).toBe(false);
});

it("passes the CSV body unchanged and preserves all five UI request variants", async () => {
  const file = new Blob(
    ["\uFEFFplayer_name,effective_weight,cycle\r\nFixture,179000,2026-11\r\n"],
    { type: "text/csv" },
  );
  fetchCsv.mockImplementation(async () => ({
    ok: true,
    headers: { get: () => "text/csv" },
    blob: async () => file,
  }));
  await render();
  for (const [kind, basis] of [
    ["accounts", "current"],
    ["accounts", "published"],
    ["participation", "current"],
    ["participation-history", "current"],
    ["bonus-history", "current"],
  ]) {
    if (select("Show").value !== kind) await change("Show", kind);
    if (kind === "accounts") await change("Roster version", basis);
    await act(async () => button("Download CSV").click());
    await settle();
    expect(fetchCsv).toHaveBeenLastCalledWith(
      `/api/cwl/seasons/1/export.csv?kind=${kind}&basis=${basis}`,
      expect.objectContaining({
        credentials: "same-origin",
        signal: expect.any(AbortSignal),
      }),
    );
    expect(URL.createObjectURL).toHaveBeenLastCalledWith(file);
  }
  expect(fetchCsv).toHaveBeenCalledTimes(5);
  expect(api.mock.calls.every((c) => c[1] === undefined)).toBe(true);
});

it("offers one download retry after failure and blocks duplicate pending requests", async () => {
  let finish: (value: unknown) => void = () => {};
  fetchCsv.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await render();
  await act(async () => {
    button("Download CSV").click();
    button("Download CSV").click();
  });
  expect(fetchCsv).toHaveBeenCalledTimes(1);
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
  fetchCsv.mockResolvedValue({
    ok: true,
    headers: { get: () => "text/csv" },
    blob: async () => new Blob(["179000"]),
  });
  await act(async () => button("Retry").click());
  await settle();
  expect(fetchCsv).toHaveBeenCalledTimes(2);
});

it.each([401, 403])(
  "hides Retry and clears protected preview after denied download %i",
  async (status) => {
    fetchCsv.mockResolvedValue({
      ok: false,
      status,
      json: async () => ({ error: "Denied" }),
    });
    const changed = vi.spyOn(window, "dispatchEvent");
    await render();
    await act(async () => button("Download CSV").click());
    await settle();
    expect(host.textContent).toContain(
      "You do not have access to this export.",
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

it("aborts an in-flight CSV when changing season and does not offer its stale Blob", async () => {
  let finish: (value: unknown) => void = () => {};
  fetchCsv.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await render();
  await act(async () => button("Download CSV").click());
  const signal = fetchCsv.mock.calls[0][1].signal as AbortSignal;
  await render("2");
  expect(signal.aborted).toBe(true);
  await act(async () =>
    finish({
      ok: true,
      headers: { get: () => "text/csv" },
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
