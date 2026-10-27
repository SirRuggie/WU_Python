export const COMPARISON_INTERVAL = 300_000;
export const COMPARISON_FOLLOWUP = 2_000;
export const COMPARISON_CYCLE_LIMIT = 90_000;

/** One active cycle, bounded follow-ups, no automatic forced reads. */
export function createComparisonChecks(
  check: (force: boolean, signal: AbortSignal) => Promise<boolean>,
  busy: (value: boolean) => void,
  initialLast = -Infinity,
  onStart: (time: number) => void = () => {},
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
    if (followup && Date.now() - started >= COMPARISON_CYCLE_LIMIT) {
      busy(false);
      schedule(last + COMPARISON_INTERVAL - Date.now());
      return;
    }
    if (!followup) {
      last = started = Date.now();
      onStart(last);
    }
    const id = generation;
    controller = new AbortController();
    pending = true;
    busy(true);
    let updating = false;
    try {
      updating = await check(force, controller.signal);
    } catch {
      /* The caller owns visible error feedback. */
    }
    if (disposed || !active || id !== generation) return;
    pending = false;
    if (
      updating &&
      Date.now() - started + COMPARISON_FOLLOWUP < COMPARISON_CYCLE_LIMIT
    ) {
      schedule(COMPARISON_FOLLOWUP, true);
    } else {
      busy(false);
      schedule(last + COMPARISON_INTERVAL - Date.now());
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
