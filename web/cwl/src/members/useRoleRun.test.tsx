// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
vi.mock("../api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api } from "../api";
import useRoleRun, { type RoleReview } from "./useRoleRun";
const review: RoleReview = {
  token: "review",
  selected: ["111111111111111111", "222222222222222222"],
  count: 2,
  role: { id: "333333333333333333", name: "Officer", protected: false },
  operation: "remove",
};
const status = {
  run_id: "run",
  state: "queued",
  rows: review.selected.map((discord_id) => ({
    discord_id,
    status: "waiting",
    message: "",
  })),
};
let host: HTMLDivElement,
  root: ReturnType<typeof createRoot>,
  latest: ReturnType<typeof useRoleRun>;
function Harness() {
  latest = useRoleRun(
    () => {},
    () => {},
  );
  return <p>{latest.error}</p>;
}
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
  vi.useRealTimers();
});
it("sends exactly the reviewed IDs and one write despite a second tap", async () => {
  let release: (value: { run_id: string; state: string }) => void = () => {};
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (method === "POST")
      return await new Promise((resolve) => {
        release = resolve;
      });
    if (path.includes("active=1")) return { runs: [] };
    return status;
  });
  await act(async () => root.render(<Harness />));
  let first: Promise<boolean>;
  await act(async () => {
    first = latest.confirm(review);
    expect(await latest.confirm(review)).toBe(false);
  });
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(1);
  expect(
    vi.mocked(api).mock.calls.find((call) => call[1] === "POST")?.[2],
  ).toEqual({
    token: "review",
    selected: review.selected,
    protected_confirmed: false,
  });
  await act(async () => {
    release({ run_id: "run", state: "queued" });
    await first!;
  });
  expect(latest.run?.rows).toHaveLength(2);
});
it("an uncertain confirm is not retried; safe progress refresh recovers its run", async () => {
  let active = false;
  vi.mocked(api).mockImplementation(async (path, method) => {
    if (method === "POST") {
      active = true;
      throw new Error("response lost");
    }
    if (path.includes("active=1"))
      return { runs: active ? [{ run_id: "run" }] : [] };
    return status;
  });
  await act(async () => root.render(<Harness />));
  await act(async () => {
    expect(await latest.confirm(review)).toBe(false);
  });
  expect(host.textContent).toContain("could not be confirmed");
  await act(async () => {
    expect(await latest.confirm(review)).toBe(false);
  });
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(1);
  await act(async () => latest.refresh());
  expect(latest.run?.run_id).toBe("run");
  expect(
    vi.mocked(api).mock.calls.filter((call) => call[1] === "POST"),
  ).toHaveLength(1);
});
