import { useEffect, useMemo, useSyncExternalStore } from "react";
import { FillerMarkQueue } from "./fillerMarkQueue";

export function useFillerQueueVersion(queue?: FillerMarkQueue) {
  return useSyncExternalStore(
    queue?.subscribe || noopSubscribe,
    queue?.snapshot || zero,
  );
}
const noopSubscribe = () => () => {};
const zero = () => 0;

export default function useFillerMarkQueue(seasonId: string) {
  const queue = useMemo(() => new FillerMarkQueue(seasonId, 0), [seasonId]);
  useFillerQueueVersion(queue);
  useEffect(() => {
    queue.activate();
    return () => queue.dispose();
  }, [queue]);
  return queue;
}
