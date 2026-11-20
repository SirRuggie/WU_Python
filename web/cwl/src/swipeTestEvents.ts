/** Fixture events only; native touch/scroll browser proof is recorded separately. */
export function touchEvent(
  node: EventTarget,
  type: "touchstart" | "touchend" | "touchcancel",
  points: { clientX: number; clientY: number }[],
  remaining: { clientX: number; clientY: number }[] = [],
) {
  const event = new Event(type, { bubbles: true, cancelable: true });
  Object.defineProperties(event, {
    touches: { value: type === "touchstart" ? points : remaining },
    changedTouches: { value: points },
  });
  node.dispatchEvent(event);
  return event;
}
export function swipeEvent(node: EventTarget, fromX = 250, toX = 100, dy = 0) {
  touchEvent(node, "touchstart", [{ clientX: fromX, clientY: 200 }]);
  return touchEvent(node, "touchend", [{ clientX: toX, clientY: 200 + dy }]);
}
