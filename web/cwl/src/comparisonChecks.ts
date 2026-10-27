export const COMPARISON_INTERVAL = 300_000;
export const COMPARISON_FOLLOWUP = 2_000;
export const COMPARISON_CYCLE_LIMIT = 90_000;

/** Only completed reads advance freshness. Cancellation never consumes a check. */
export function createComparisonChecks(
  check: (force: boolean, signal: AbortSignal) => Promise<boolean>,
  busy: (value: boolean) => void,
  initialLast = -Infinity,
  onCompleted: (time: number) => void = () => {},
) {
  let active = false;
  let disposed = false;
  let last = initialLast;
  let started = 0;
  let generation = 0;
  let pending = false;
  let controller: AbortController | undefined;
  let timer: ReturnType<typeof setTimeout> | undefined;
  const cancel = () => {
    generation++;
    clearTimeout(timer);
    controller?.abort();
    pending = false;
    busy(false);
  };
  const schedule = (delay: number, followup = false) => {
    clearTimeout(timer);
    timer = setTimeout(() => void run(false, followup), Math.max(0, delay));
  };
  async function run(force: boolean, followup = false) {
    if (!active || disposed || pending) return;
    if (!followup) started = Date.now();
    const id = generation;
    const request = new AbortController();
    controller = request;
    pending = true;
    busy(true);
    let updating = false;
    let completed = false;
    try {
      updating = await check(force, request.signal);
      completed = !request.signal.aborted;
    } catch {
      // Visible errors belong to the caller; an empty first load gets bounded retries.
    }
    if (disposed || !active || id !== generation) return;
    pending = false;
    if (completed) {
      last = Date.now();
      onCompleted(last);
    }
    const needsFollowup = updating || (!completed && !Number.isFinite(last));
    if (
      needsFollowup &&
      Date.now() - started + COMPARISON_FOLLOWUP < COMPARISON_CYCLE_LIMIT
    ) {
      schedule(COMPARISON_FOLLOWUP, true);
    } else {
      busy(false);
      // A failed first cycle must not spin at a negative/infinite deadline.
      schedule(COMPARISON_INTERVAL);
    }
  }
  return {
    setActive(value: boolean) {
      if (active === value || disposed) return;
      active = value;
      if (!value) cancel();
      else if (Date.now() - last >= COMPARISON_INTERVAL) void run(false);
      else schedule(last + COMPARISON_INTERVAL - Date.now());
    },
    refresh() {
      if (active && !pending) void run(true);
    },
    dispose() {
      disposed = true;
      active = false;
      cancel();
    },
  };
}
