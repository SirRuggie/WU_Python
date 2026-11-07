import { useCallback, useLayoutEffect, useState } from "react";

// Reveal a restored/changed selection in its own strip, never in the page.
export default function useChoiceGroupScroll<T extends HTMLElement>(
  selection: string | number,
  enabled = true,
  externalRef?: (node: T | null) => void,
) {
  const [element, setElement] = useState<T | null>(null);
  const ref = useCallback(
    (node: T | null) => {
      if (enabled) setElement(node);
      externalRef?.(node);
    },
    [enabled, externalRef],
  );
  useLayoutEffect(() => {
    if (!enabled || !element) return;
    const reveal = () => {
      const selected = element.querySelector<HTMLElement>(
        ':scope > [aria-pressed="true"], :scope > [aria-selected="true"], :scope > [aria-current="page"], :scope > [aria-current="step"]',
      );
      if (!selected || element.scrollWidth <= element.clientWidth) return;
      const box = element.getBoundingClientRect();
      const item = selected.getBoundingClientRect();
      const style = getComputedStyle(element);
      const left =
        box.left + element.clientLeft + (parseFloat(style.paddingLeft) || 0);
      const right =
        box.left +
        element.clientLeft +
        element.clientWidth -
        (parseFloat(style.paddingRight) || 0);
      const delta =
        item.left < left
          ? item.left - left
          : item.right > right
            ? item.right - right
            : 0;
      if (delta)
        element.scrollLeft = Math.max(
          0,
          Math.min(
            element.scrollWidth - element.clientWidth,
            element.scrollLeft + delta,
          ),
        );
    };
    reveal();
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(reveal);
    observer?.observe(element);
    for (const child of element.children) observer?.observe(child);
    return () => observer?.disconnect();
  }, [element, enabled, selection]);
  return ref;
}
