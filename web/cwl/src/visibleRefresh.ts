/** Existing UI refresh cadence, suspended offscreen; no data or authority cache. */
export function visibleRefresh(
  refresh: () => unknown | Promise<unknown>,
  intervalMs: number,
  { focus = false }: { focus?: boolean } = {},
) {
  let disposed = false;
  let pending = false;
  let interval: ReturnType<typeof setInterval> | undefined;
  let burst: ReturnType<typeof setTimeout> | undefined;
  let catchUpQueued = false;
  const stop = () => {
    if (interval !== undefined) clearInterval(interval);
    if (burst !== undefined) clearTimeout(burst);
    interval = undefined;
    burst = undefined;
  };
  const request = (catchUp = false) => {
    if (disposed || document.hidden || pending) return;
    catchUpQueued ||= catchUp;
    if (burst !== undefined) return;
    // Neighboring focus/visibility/interval browser tasks share one short burst.
    burst = setTimeout(() => {
      burst = undefined;
      if (disposed || document.hidden || pending) return;
      if (catchUpQueued) {
        if (interval !== undefined) clearInterval(interval);
        interval = undefined;
        start();
      }
      catchUpQueued = false;
      pending = true;
      const done = () => {
        pending = false;
      };
      try {
        // The page still owns errors/status and stale-scope handling.
        Promise.resolve(refresh()).then(done, done);
      } catch (error) {
        done();
        throw error;
      }
    }, 32);
  };
  const start = () => {
    if (!disposed && !document.hidden && interval === undefined)
      interval = setInterval(() => request(), intervalMs);
  };
  const visible = () => {
    if (document.hidden) stop();
    else {
      start();
      request(true);
    }
  };
  const onFocus = () => request(true);
  start();
  document.addEventListener("visibilitychange", visible);
  if (focus) window.addEventListener("focus", onFocus);
  return () => {
    disposed = true;
    stop();
    document.removeEventListener("visibilitychange", visible);
    if (focus) window.removeEventListener("focus", onFocus);
  };
}
