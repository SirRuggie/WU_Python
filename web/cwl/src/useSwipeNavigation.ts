import {
  useCallback,
  useEffect,
  useRef,
  type MouseEvent,
  type RefCallback,
} from "react";
import "./useSwipeNavigation.css";

export const SWIPE_DISTANCE = 70;
export const SWIPE_AXIS_RATIO = 1.5;
export const SWIPE_EDGE_GUARD = 24;
export type SwipeDirection = "next" | "previous";

/** Discrete, touch-only navigation; browser scrolling and pinch zoom stay native. */
export default function useSwipeNavigation<
  T extends HTMLElement = HTMLDivElement,
>({
  onSwipe,
  enabled = true,
}: {
  onSwipe: (direction: SwipeDirection) => void;
  enabled?: boolean;
}) {
  const latest = useRef({ onSwipe, enabled });
  latest.current = { onSwipe, enabled };
  const start = useRef<{ node: T; x: number; y: number } | null>(null);
  const blockClick = useRef(false);
  useEffect(() => {
    if (!enabled) {
      start.current = null;
      blockClick.current = false;
    }
  }, [enabled]);
  useEffect(() => {
    // A second finger may land outside the swipe area. Cancel the original
    // gesture there too, without intercepting the browser's pinch/scroll input.
    const additionalTouch = (event: TouchEvent) => {
      if (event.touches.length > 1) start.current = null;
    };
    document.addEventListener("touchstart", additionalTouch, { passive: true });
    return () => document.removeEventListener("touchstart", additionalTouch);
  }, []);
  const ref = useCallback<RefCallback<T>>((node) => {
    if (!node) return;
    const touchStart = (event: TouchEvent) => {
      start.current = null;
      blockClick.current = false;
      if (!latest.current.enabled || event.touches.length !== 1) return;
      const point = event.touches[0];
      if (
        point.clientX < SWIPE_EDGE_GUARD ||
        point.clientX > window.innerWidth - SWIPE_EDGE_GUARD ||
        (window.visualViewport?.scale ?? 1) > 1.01
      )
        return;
      start.current = { node, x: point.clientX, y: point.clientY };
    };
    const touchEnd = (event: TouchEvent) => {
      const point = start.current;
      start.current = null;
      if (
        !point ||
        point.node !== node ||
        !latest.current.enabled ||
        event.touches.length !== 0 ||
        event.changedTouches.length !== 1 ||
        (window.visualViewport?.scale ?? 1) > 1.01 ||
        window.getSelection()?.toString()
      )
        return;
      const dx = event.changedTouches[0].clientX - point.x;
      const dy = event.changedTouches[0].clientY - point.y;
      if (
        Math.abs(dx) <= SWIPE_DISTANCE ||
        Math.abs(dx) <= SWIPE_AXIS_RATIO * Math.abs(dy)
      )
        return;
      blockClick.current = true;
      latest.current.onSwipe(dx < 0 ? "next" : "previous");
    };
    const touchCancel = () => {
      start.current = null;
    };
    // React19 callback-ref cleanup supports both a single area and Compare's
    // multiple clan lists. The click block spans them when the visible list changes.
    node.addEventListener("touchstart", touchStart, { passive: true });
    node.addEventListener("touchend", touchEnd, { passive: true });
    node.addEventListener("touchcancel", touchCancel, { passive: true });
    return () => {
      node.removeEventListener("touchstart", touchStart);
      node.removeEventListener("touchend", touchEnd);
      node.removeEventListener("touchcancel", touchCancel);
      if (start.current?.node === node) start.current = null;
    };
  }, []);
  const onClickCapture = useCallback((event: MouseEvent<T>) => {
    if (!blockClick.current) return;
    blockClick.current = false;
    event.preventDefault();
    event.stopPropagation();
  }, []);
  return { ref, onClickCapture };
}
