// @vitest-environment happy-dom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, it, expect, vi } from "vitest";
vi.mock("./api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api, ApiError } from "./api";
import useRefresh, {
  mergeIdentityAccounts,
  type IdentitySnapshot,
} from "./useActivityIdentityRefresh";
import type { ActivityAccount } from "./strikeActivityView";
let root: Root, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  vi.useFakeTimers();
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
function Fixture({
  result,
  denied,
}: {
  result: (value: IdentitySnapshot) => void;
  denied: () => void;
}) {
  useRefresh({
    enabled: true,
    generation: 1,
    busy: () => false,
    onResult: result,
    onDenied: denied,
  });
  return null;
}
it("refreshes names automatically and stops when the background job completes", async () => {
  vi.mocked(api).mockResolvedValue({ accounts: [], identity_updating: false });
  const result = vi.fn(),
    denied = vi.fn();
  await act(async () =>
    root.render(<Fixture result={result} denied={denied} />),
  );
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(result).toHaveBeenCalledOnce();
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(api).toHaveBeenCalledTimes(1);
});
it("bounds an always-pending source and clears access on403", async () => {
  vi.mocked(api).mockResolvedValue({ accounts: [], identity_updating: true });
  const result = vi.fn(),
    denied = vi.fn();
  await act(async () =>
    root.render(<Fixture result={result} denied={denied} />),
  );
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(api).toHaveBeenCalledTimes(6);
  await act(async () => root.unmount());
  root = createRoot(host);
  vi.mocked(api).mockReset().mockRejectedValue(new ApiError("Denied", 403));
  await act(async () =>
    root.render(<Fixture result={result} denied={denied} />),
  );
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(denied).toHaveBeenCalledOnce();
});
it("does not apply a late name result after unmount", async () => {
  let resolve!: (value: unknown) => void;
  vi.mocked(api).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  const result = vi.fn();
  await act(async () =>
    root.render(<Fixture result={result} denied={vi.fn()} />),
  );
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  await act(async () => root.unmount());
  root = createRoot(host);
  await act(async () => resolve({ accounts: [], identity_updating: false }));
  expect(result).not.toHaveBeenCalled();
});
it("merges only identity fields without replacing records, notes or selections", () => {
  const row = {
    player_tag: "#PYY",
    active_strikes: 3,
    revision: 7,
    replacement_note: "Draft",
    discord_name: null,
  } as ActivityAccount;
  const merged = mergeIdentityAccounts(
    [row],
    [
      {
        ...row,
        active_strikes: 99,
        revision: 99,
        replacement_note: "Wrong",
        discord_name: "New name",
      },
      { player_tag: "#PQQ" } as ActivityAccount,
    ],
  );
  expect(merged).toEqual([
    { ...row, discord_id: undefined, discord_name: "New name" },
  ]);
  expect(row.discord_name).toBeNull();
});
