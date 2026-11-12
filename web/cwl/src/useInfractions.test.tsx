// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
const api = vi.hoisted(() => vi.fn());
vi.mock("./api", async (original) => ({ ...(await original<object>()), api }));
import useInfractions, { type Infractions } from "./useInfractions";
import type { BonusStatus } from "./bonusStatus";

const raffle = {
  revision: 4,
  cycle: "2026-11",
  season_status: "draft",
  draws: [],
  accounts: [],
};
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
let current: Infractions;
function Probe(props: {
  canManage?: boolean;
  archived?: boolean;
  status?: BonusStatus | null;
  onSaved?: () => void;
}) {
  current = useInfractions(
    "1",
    props.canManage ?? true,
    props.archived ?? false,
    props.status ?? null,
    props.onSaved,
  );
  return null;
}
const mount = (props: Parameters<typeof Probe>[0] = {}) =>
  act(async () => root.render(<Probe {...props} />));
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset().mockResolvedValue(raffle);
  host = document.createElement("div");
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
});

it("reads nothing until load is called, then reads the season once", async () => {
  await mount();
  expect(api).not.toHaveBeenCalled();
  await act(async () => current.load());
  expect(api).toHaveBeenCalledTimes(1);
  expect(api).toHaveBeenCalledWith("/seasons/1/bonus-raffle");
  expect(current.data).toEqual(raffle);
});

it("reports a failed read and recovers on retry", async () => {
  api.mockRejectedValueOnce(new Error("down"));
  await mount();
  await act(async () => current.load());
  expect(current.state).toBe("failed");
  await act(async () => current.load());
  expect(current.state).toBe("idle");
  expect(current.data).toEqual(raffle);
});

it("saves with the same PATCH and revision, then keeps the fresh data", async () => {
  await mount();
  await act(async () => current.load());
  api.mockResolvedValueOnce({ ...raffle, revision: 5 });
  await act(async () => current.save("#P1", ["lingering"], "Played"));
  expect(api).toHaveBeenLastCalledWith(
    "/seasons/1/bonus-raffle/account-review",
    "PATCH",
    {
      tag: "#P1",
      flags: ["lingering"],
      override_reason: "Played",
      revision: 4,
    },
  );
  expect(current.data?.revision).toBe(5);
});

it("tells the page after a save, and not after a failed one", async () => {
  const onSaved = vi.fn();
  await mount({ onSaved });
  await act(async () => current.load());
  api.mockRejectedValueOnce(new Error("no"));
  await act(async () => {
    await current.save("#P1", [], "").catch(() => {});
  });
  expect(onSaved).not.toHaveBeenCalled();
  await act(async () => current.save("#P1", ["lingering"], ""));
  expect(onSaved).toHaveBeenCalledTimes(1);
});

it("locks after a draw, for archived seasons and without the manage grant", async () => {
  const drawn = {
    pools: { main: [], lazy: [{ tag: "#H", draw_state: "saved" }] },
  } as unknown as BonusStatus;
  await mount({ status: drawn });
  expect(current.lock("#H")).toBe("draw");
  expect(current.lock("#OTHER")).toBeNull();
  await mount({ canManage: false });
  expect(current.lock("#H")).toBe("locked");
  await mount({ archived: true });
  expect(current.lock("#H")).toBe("locked");
});
