import {
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";

/** Per-signed-in-app memory, never persisted or shared between users. */
export type ViewMemory = Map<string, unknown>;
export function useViewState<T>(
  memory: ViewMemory | undefined,
  key: string,
  initial: T,
): [T, Dispatch<SetStateAction<T>>] {
  const [value, setValue] = useState<T>(() =>
    memory?.has(key) ? (memory.get(key) as T) : initial,
  );
  useEffect(() => {
    memory?.set(key, value);
  }, [memory, key, value]);
  return [value, setValue];
}
export function useViewScroll(memory: ViewMemory | undefined, ready: boolean) {
  const restore = useRef(
    typeof memory?.get("scroll") === "number"
      ? (memory.get("scroll") as number)
      : 0,
  );
  const restored = useRef(false);
  useEffect(() => {
    if (!ready || restored.current) return;
    let frame = 0;
    const apply = () => {
      if (
        restore.current > 0 &&
        document.documentElement.scrollHeight - window.innerHeight <
          restore.current
      )
        return;
      window.scrollTo(0, restore.current);
      restored.current = true;
      observer.disconnect();
    };
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(apply);
    });
    observer.observe(document.body);
    frame = requestAnimationFrame(apply);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [ready]);
  useLayoutEffect(() => {
    const save = () => {
      if (restored.current) memory?.set("scroll", window.scrollY);
    };
    window.addEventListener("scroll", save, { passive: true });
    return () => {
      window.removeEventListener("scroll", save);
    };
  }, [memory]);
}
