// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
import ExportDownloads from "./ExportDownloads";
const { fetchReadWithRetry } = vi.hoisted(() => ({
  fetchReadWithRetry: vi.fn(),
}));
vi.mock("./readRetry", () => ({ fetchReadWithRetry }));
let host: HTMLDivElement, root: Root;
const seasons = Array.from({ length: 14 }, (_, i) => ({
  id: i + 1,
  label: `${2025 + Math.floor((i + 10) / 12)}-${String(((i + 10) % 12) + 1).padStart(2, "0")}`,
  status: "draft",
  signup_open: false,
}));
const onDenied = vi.fn();
const render = async (canDownload = true, seasonId = "1") => {
  await act(async () =>
    root.render(
      <ExportDownloads
        seasonId={seasonId}
        seasons={seasons}
        basis="published"
        ready={true}
        canDownload={canDownload}
        onDenied={onDenied}
      />,
    ),
  );
};
const button = (text: string) =>
  [...host.querySelectorAll("button")].find((el) => el.textContent === text)!;
const open = async (value = true) => {
  await act(async () => {
    const details = host.querySelector("details")!;
    details.open = value;
    details.dispatchEvent(new Event("toggle"));
  });
};
const set = async (name: string, value: string) => {
  await act(async () => {
    const el = host.querySelector(
      `select[name="${name}"]`,
    ) as HTMLSelectElement;
    el.value = value;
    el.dispatchEvent(new Event("change", { bubbles: true }));
  });
};
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  fetchReadWithRetry.mockReset();
  onDenied.mockReset();
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  vi.stubGlobal(
    "URL",
    class extends URL {
      static createObjectURL = vi.fn(() => "blob:fixture");
      static revokeObjectURL = vi.fn();
    },
  );
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
it("hides all workbook controls without winner access", async () => {
  await render(false);
  expect(host.textContent).toBe("");
  expect(fetchReadWithRetry).not.toHaveBeenCalled();
});
it("opens quiet range controls without a fetch and validates calendar span and order", async () => {
  await render();
  expect(host.querySelector("select")).toBeNull();
  await open();
  expect(host.querySelectorAll("select")).toHaveLength(2);
  expect(fetchReadWithRetry).not.toHaveBeenCalled();
  await set("export-from", seasons[0].label);
  expect(host.textContent).toContain("no more than 12 calendar months");
  expect(button("Download range").disabled).toBe(true);
  await set("export-from", seasons[13].label);
  await set("export-to", seasons[0].label);
  expect(host.textContent).toContain("To must be on or after From");
});
it.each([404, 409])(
  "shows named range failure %i under controls and allows deliberate retry",
  async (status) => {
    await render();
    await open();
    fetchReadWithRetry.mockResolvedValueOnce({
      ok: false,
      status,
      json: async () => ({
        error: "No saved season for August 2026, September 2026",
      }),
    });
    await act(async () => button("Download range").click());
    expect(
      host.querySelector(".export-range-fields [role=alert]")?.textContent,
    ).toContain("August 2026, September 2026");
    expect(URL.createObjectURL).not.toHaveBeenCalled();
    expect(fetchReadWithRetry).toHaveBeenCalledTimes(1);
    expect(button("Retry range")).toBeDefined();
  },
);
it("aborts range on close and ignores its late body", async () => {
  let finish: (value: unknown) => void = () => {};
  fetchReadWithRetry.mockImplementationOnce(
    () =>
      new Promise((resolve) => {
        finish = resolve;
      }),
  );
  await render();
  await open();
  await act(async () => {
    button("Download range").click();
    button("Download range")?.click();
  });
  expect(fetchReadWithRetry).toHaveBeenCalledTimes(1);
  const signal = fetchReadWithRetry.mock.calls[0][1].signal as AbortSignal;
  await open(false);
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
  expect(host.querySelector("select")).toBeNull();
});
it("range success passes the exact months and offers the original workbook Blob", async () => {
  const file = new Blob(["fixture workbook"]);
  fetchReadWithRetry.mockResolvedValue({
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
  await open();
  await set("export-from", "2026-08");
  await set("export-to", "2026-11");
  await act(async () => button("Download range").click());
  expect(fetchReadWithRetry).toHaveBeenLastCalledWith(
    "/api/cwl/exports/range.xlsx?from=2026-08&to=2026-11",
    expect.objectContaining({
      credentials: "same-origin",
      signal: expect.any(AbortSignal),
    }),
  );
  expect(URL.createObjectURL).toHaveBeenCalledWith(file);
  expect(host.textContent).toContain("Excel download started");
});
