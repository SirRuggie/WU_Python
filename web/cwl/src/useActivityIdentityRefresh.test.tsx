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
  generation = 1,
  busy = () => false,
}: {
  result: (value: IdentitySnapshot) => void;
  denied: () => void;
  generation?: number;
  busy?: () => boolean;
}) {
  useRefresh({
    enabled: true,
    generation,
    busy,
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

it("abandons an in-flight identity result when the generation changes", async () => {
  let resolveOld!: (value: unknown) => void;
  vi.mocked(api)
    .mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolveOld = done;
        }),
    )
    .mockResolvedValueOnce({
      accounts: [],
      identity_updating: false,
      identity_warning: "new generation",
    });
  const result = vi.fn(),
    denied = vi.fn();
  await act(async () =>
    root.render(<Fixture result={result} denied={denied} generation={1} />),
  );
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  await act(async () =>
    root.render(<Fixture result={result} denied={denied} generation={2} />),
  );
  await act(async () =>
    resolveOld({
      accounts: [],
      identity_updating: false,
      identity_warning: "old generation",
    }),
  );
  expect(result).not.toHaveBeenCalled();
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(result).toHaveBeenCalledTimes(1);
  expect(result.mock.calls[0][0].identity_warning).toBe("new generation");
  expect(api).toHaveBeenCalledTimes(2);
});
it("defers identity reads while an edit is busy without consuming the poll budget", async () => {
  let busy = true;
  const result = vi.fn();
  vi.mocked(api).mockResolvedValue({ accounts: [], identity_updating: false });
  await act(async () =>
    root.render(<Fixture result={result} denied={vi.fn()} busy={() => busy} />),
  );
  await act(async () => vi.advanceTimersByTimeAsync(20000));
  expect(api).not.toHaveBeenCalled();
  busy = false;
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(api).toHaveBeenCalledTimes(1);
  expect(result).toHaveBeenCalledOnce();
});

it("recovers automatically after the server failure cooldown without reload", async () => {
  vi.mocked(api)
    .mockResolvedValueOnce({
      accounts: [],
      identity_updating: false,
      identity_warning: "Temporarily unavailable",
    })
    .mockResolvedValueOnce({
      accounts: [{ player_tag: "#PYY", discord_name: "Recovered" }],
    });
  const result = vi.fn();
  await act(async () =>
    root.render(<Fixture result={result} denied={vi.fn()} />),
  );
  await act(async () => vi.advanceTimersByTimeAsync(2000));
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(119000));
  expect(api).toHaveBeenCalledTimes(1);
  await act(async () => vi.advanceTimersByTimeAsync(1000));
  expect(api).toHaveBeenCalledTimes(2);
  expect(result.mock.calls.at(-1)![0].accounts[0].discord_name).toBe(
    "Recovered",
  );
  await act(async () => vi.advanceTimersByTimeAsync(120000));
  expect(api).toHaveBeenCalledTimes(2);
});
