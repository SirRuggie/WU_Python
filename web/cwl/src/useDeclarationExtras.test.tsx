// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
const mock = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api: mock.api }));
import useDeclarationExtras from "./useDeclarationExtras";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
let current: ReturnType<typeof useDeclarationExtras>;
function Probe({
  basis = 1,
  source = "published",
}: {
  basis?: number;
  source?: "published" | "draft";
}) {
  current = useDeclarationExtras("1", source, basis, true);
  return (
    <div>
      {current.loading ? "checking" : current.error || current.data?.basis}
    </div>
  );
}
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  mock.api.mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
});
it("loads once and only explicitly refreshes, without periodic polling", async () => {
  vi.useFakeTimers();
  mock.api.mockResolvedValue({ source: "published", basis: 1, clans: [] });
  await act(async () => root.render(<Probe />));
  expect(mock.api).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTime(900000));
  expect(mock.api).toHaveBeenCalledTimes(1);
  await act(async () => current.refresh());
  expect(mock.api).toHaveBeenCalledTimes(2);
  expect(mock.api.mock.calls[1][0]).toContain("&refresh=1");
});
it("ignores old source replies and clears prior data after an unavailable read", async () => {
  let old!: (value: unknown) => void;
  mock.api.mockImplementationOnce(
    () => new Promise((resolve) => (old = resolve)),
  );
  await act(async () => root.render(<Probe />));
  expect(host.textContent).toBe("checking");
  mock.api.mockResolvedValue({ source: "draft", basis: 2, clans: [] });
  await act(async () => root.render(<Probe source="draft" basis={2} />));
  await act(async () => old({ source: "published", basis: 1, clans: [] }));
  expect(host.textContent).toBe("2");
  mock.api.mockRejectedValue(new Error("fixture failure"));
  await act(async () => current.refresh());
  expect(host.textContent).toBe("Couldn't check clan members");
  expect(current.data).toBeUndefined();
});

it("two quick receipt updates keep both members and mark revisions without fetching", async () => {
  mock.api.mockResolvedValue({
    source: "published",
    basis: 1,
    revision: 1,
    clans: [
      {
        tag: "A",
        status: "current",
        checked_at: "now",
        extras: [
          { tag: "X", name: "X", town_hall: 16 },
          { tag: "Y", name: "Y", town_hall: 16 },
        ],
        count: 2,
      },
    ],
  });
  await act(async () => root.render(<Probe />));
  await act(async () => {
    current.applyMark({
      tag: "X",
      revision: 2,
      roster_filler: true,
      mark_revision: 3,
    });
    current.applyMark({
      tag: "Y",
      revision: 3,
      roster_filler: true,
      mark_revision: 4,
    });
  });
  expect(
    current.data?.clans[0].fillers?.map((m) => [
      m.tag,
      m.roster_filler_revision,
    ]),
  ).toEqual([
    ["X", 3],
    ["Y", 4],
  ]);
  expect(current.data?.revision).toBe(3);
  expect(mock.api).toHaveBeenCalledTimes(1);
});
