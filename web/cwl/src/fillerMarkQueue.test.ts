import { expect, it, vi } from "vitest";
import { ApiError } from "./api";
import { FillerMarkQueue, type FillerRow } from "./fillerMarkQueue";
const row = (tag: string): FillerRow => ({
  tag,
  name: `Player ${tag}`,
  value: false,
  markRevision: 0,
});
const turn = async () => {
  for (let i = 0; i < 12; i++) await Promise.resolve();
};
function fixture() {
  let revision = 9;
  let inFlight = 0,
    maximum = 0;
  const saved = new Map<string, boolean>();
  const releases: (() => void)[] = [];
  const wire = vi.fn(async (path: string, _method: string, body: unknown) => {
    const input = body as {
      revision: number;
      roster_filler: boolean;
      mark_revision: number;
    };
    inFlight++;
    maximum = Math.max(maximum, inFlight);
    expect(input.revision).toBe(revision);
    const tag = decodeURIComponent(path.split("/").at(-1)!);
    const markRevision = Number(saved.has(tag));
    expect(input.mark_revision).toBe(markRevision);
    revision++;
    saved.set(tag, input.roster_filler);
    await new Promise<void>((resolve) => releases.push(resolve));
    inFlight--;
    return {
      tag,
      revision,
      roster_filler: input.roster_filler,
      mark_revision: markRevision + 1,
    };
  });
  const queue = new FillerMarkQueue("1", 9, wire);
  const flush = vi.fn(),
    denied = vi.fn();
  queue.configure(flush, denied);
  return {
    queue,
    wire,
    flush,
    denied,
    saved,
    releases,
    maximum: () => maximum,
  };
}
it("saves ten fast rows serially with each previous confirmed revision, optimistic state and one regroup flush", async () => {
  const f = fixture();
  for (let i = 0; i < 10; i++) f.queue.enqueue(row(`#${i}`), true);
  expect(f.queue.working).toBe(true);
  expect(f.queue.row("#9")?.value).toBe(true);
  await turn();
  expect(f.wire).toHaveBeenCalledTimes(1);
  expect(f.flush).not.toHaveBeenCalled();
  for (let i = 0; i < 10; i++) {
    f.releases.shift()!();
    await turn();
  }
  expect(f.maximum()).toBe(1);
  expect(f.saved.size).toBe(10);
  expect(
    f.wire.mock.calls.map((c) => (c[2] as { revision: number }).revision),
  ).toEqual([9, 10, 11, 12, 13, 14, 15, 16, 17, 18]);
  expect(f.flush).toHaveBeenCalledTimes(1);
  expect(f.flush.mock.calls[0][0]).toHaveLength(10);
  expect(f.queue.working).toBe(false);
  expect(f.queue.latestRevision).toBe(19);
});
it("coalesces an unsent tick then untick into no request", async () => {
  const f = fixture();
  f.queue.enqueue(row("#A"), true);
  f.queue.enqueue(row("#A"), false);
  await turn();
  expect(f.wire).not.toHaveBeenCalled();
  expect(f.queue.row("#A")?.value).toBe(false);
});
it("uses latest same-row mark revision after an in-flight tick then untick", async () => {
  const f = fixture();
  f.queue.enqueue(row("#A"), true);
  await turn();
  f.queue.enqueue(row("#A"), false);
  expect(f.queue.row("#A")?.value).toBe(false);
  f.releases.shift()!();
  await turn();
  expect(f.wire).toHaveBeenCalledTimes(2);
  expect(f.wire.mock.calls[1][2]).toEqual({
    revision: 10,
    roster_filler: false,
    mark_revision: 1,
  });
  f.releases.shift()!();
  await turn();
  expect(f.saved.get("#A")).toBe(false);
  expect(f.flush).toHaveBeenCalledTimes(1);
});
it("last same-row state equal to in-flight target sends no redundant write", async () => {
  const f = fixture();
  f.queue.enqueue(row("#A"), true);
  await turn();
  f.queue.enqueue(row("#A"), false);
  f.queue.enqueue(row("#A"), true);
  f.releases.shift()!();
  await turn();
  expect(f.wire).toHaveBeenCalledTimes(1);
  expect(f.queue.row("#A")?.value).toBe(true);
});
it.each([409, 401, 403, 0])(
  "halts on%s without retry or draining remaining rows, retaining confirmed rows and listing every unsaved row",
  async (status) => {
    let calls = 0;
    const flush = vi.fn(),
      denied = vi.fn();
    const wire = vi.fn(async (_p: string, _m: string, b: unknown) => {
      calls++;
      if (calls === 2) throw new ApiError("Raw Reference: secret", status);
      return {
        revision: 10,
        roster_filler: (b as { roster_filler: boolean }).roster_filler,
        mark_revision: 1,
      };
    });
    const q = new FillerMarkQueue("1", 9, wire);
    q.configure(flush, denied);
    for (const tag of ["#A", "#B", "#C"]) q.enqueue(row(tag), true);
    await turn();
    expect(wire).toHaveBeenCalledTimes(2);
    expect(q.row("#A")?.value).toBe(true);
    expect(q.row("#B")?.value).toBe(false);
    expect(q.row("#C")?.value).toBe(false);
    expect(q.notSaved.map((r) => r.tag)).toEqual(["#B", "#C"]);
    expect(q.blocked).toBe(true);
    q.enqueue(row("#D"), true);
    await turn();
    expect(wire).toHaveBeenCalledTimes(2);
    expect(flush.mock.calls[0][0]).toHaveLength(1);
    expect(denied).toHaveBeenCalledTimes([401, 403].includes(status) ? 1 : 0);
    expect(q.unknownOutcome).toBe(status === 0);
  },
);
it("halts a timeout with unknown outcome and never retries", async () => {
  const wire = vi.fn(async () => {
    throw new DOMException("Timeout", "TimeoutError");
  });
  const q = new FillerMarkQueue("1", 9, wire);
  q.enqueue(row("#A"), true);
  q.enqueue(row("#B"), true);
  await turn();
  expect(wire).toHaveBeenCalledTimes(1);
  expect(q.unknownOutcome).toBe(true);
  expect(q.notSaved).toHaveLength(2);
});
it("does not send queued rows after unmount while an active request settles", async () => {
  const f = fixture();
  f.queue.enqueue(row("#A"), true);
  f.queue.enqueue(row("#B"), true);
  await turn();
  f.queue.dispose();
  f.releases.shift()!();
  await turn();
  expect(f.wire).toHaveBeenCalledTimes(1);
  expect(f.flush).not.toHaveBeenCalled();
});
it("does not start even the first queued request after immediate unmount", async () => {
  const f = fixture();
  f.queue.enqueue(row("#A"), true);
  f.queue.dispose();
  await turn();
  expect(f.wire).not.toHaveBeenCalled();
});
it("requires a successful refresh to reset a halted queue and uses the new revision", async () => {
  const wire = vi
    .fn()
    .mockRejectedValueOnce(new ApiError("Conflict", 409))
    .mockResolvedValue({ revision: 25, roster_filler: true, mark_revision: 4 });
  const q = new FillerMarkQueue("1", 9, wire);
  q.enqueue(row("#A"), true);
  await turn();
  q.refreshed(24);
  q.enqueue({ ...row("#A"), markRevision: 3 }, true);
  await turn();
  expect(wire.mock.calls[1][2]).toEqual({
    revision: 24,
    roster_filler: true,
    mark_revision: 3,
  });
  expect(q.notSaved).toEqual([]);
});
it("keeps a confirmed row and newer read revision when a read advances during an in-flight save", async () => {
  let release!: (result: any) => void;
  const wire = vi
    .fn()
    .mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          release = resolve;
        }),
    )
    .mockResolvedValueOnce({
      revision: 14,
      roster_filler: true,
      mark_revision: 1,
    });
  const q = new FillerMarkQueue("1", 9, wire);
  q.enqueue(row("#A"), true);
  q.enqueue(row("#B"), true);
  await turn();
  q.syncRevision(13);
  release({ revision: 10, roster_filler: true, mark_revision: 1 });
  await turn();
  expect(wire.mock.calls[1][2]).toEqual({
    revision: 13,
    roster_filler: true,
    mark_revision: 0,
  });
  expect(q.row("#A")?.value).toBe(true);
  expect(q.latestRevision).toBe(14);
  expect(q.notSaved).toEqual([]);
});
it("bounds a hung write at45seconds, aborts its signal and never starts the next row", async () => {
  vi.useFakeTimers();
  try {
    const wire = vi.fn(() => new Promise<any>(() => {}));
    const q = new FillerMarkQueue("1", 9, wire);
    q.enqueue(row("#A"), true);
    q.enqueue(row("#B"), true);
    await turn();
    expect(wire).toHaveBeenCalledTimes(1);
    const signal = (wire.mock.calls[0] as any)[3].signal as AbortSignal;
    await vi.advanceTimersByTimeAsync(45000);
    expect(signal.aborted).toBe(true);
    expect(q.working).toBe(false);
    expect(q.blocked).toBe(true);
    expect(q.notSaved.map((row) => row.tag)).toEqual(["#A", "#B"]);
    expect(q.unknownOutcome).toBe(true);
    expect(wire).toHaveBeenCalledTimes(1);
  } finally {
    vi.useRealTimers();
  }
});
it("uses a newer observed mark revision even if a control still has older rendered props", async () => {
  const wire = vi
    .fn()
    .mockResolvedValue({ revision: 14, roster_filler: true, mark_revision: 3 });
  const q = new FillerMarkQueue("1", 13, wire);
  q.observeRows([{ ...row("#A"), markRevision: 2 }]);
  q.enqueue(row("#A"), true);
  await turn();
  expect(wire.mock.calls[0][2]).toEqual({
    revision: 13,
    roster_filler: true,
    mark_revision: 2,
  });
});
it("background observations cannot clear a failed queue or replace its known saved state", async () => {
  const q = new FillerMarkQueue(
    "1",
    9,
    vi.fn().mockRejectedValue(new ApiError("Conflict", 409)),
  );
  q.enqueue(row("#A"), true);
  await turn();
  q.observeRows([{ ...row("#A"), value: true, markRevision: 2 }]);
  expect(q.blocked).toBe(true);
  expect(q.notSaved.map((row) => row.tag)).toEqual(["#A"]);
  expect(q.row("#A")?.value).toBe(false);
});
it("blocks new ticks while another explicit revision write holds the page lock", async () => {
  const f = fixture();
  f.queue.setWriteBusy(true);
  f.queue.enqueue(row("#A"), true);
  await turn();
  expect(f.wire).not.toHaveBeenCalled();
  expect(f.queue.working).toBe(true);
  f.queue.setWriteBusy(false);
  f.queue.enqueue(row("#A"), true);
  await turn();
  expect(f.wire).toHaveBeenCalledTimes(1);
  f.releases.shift()!();
  await turn();
});
