import { useCallback, useEffect, useState } from "react";

export function horizontalFadeState(
  element: Pick<HTMLElement, "scrollLeft" | "scrollWidth" | "clientWidth">,
) {
  return {
    left: element.scrollLeft > 1,
    right: element.scrollLeft + element.clientWidth < element.scrollWidth - 1,
  };
}

export function useHorizontalFades<T extends HTMLElement>() {
  const [element, setElement] = useState<T | null>(null);
  const ref = useCallback((node: T | null) => setElement(node), []);
  const [edges, setEdges] = useState({ left: false, right: false });
  useEffect(() => {
    if (!element) return;
    const update = () => {
      const next = horizontalFadeState(element);
      setEdges((current) =>
        current.left === next.left && current.right === next.right
          ? current
          : next,
      );
    };
    update();
    element.addEventListener("scroll", update, { passive: true });
    const observer =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(update);
    const observed = new Set<Element>();
    const observeChildren = () => {
      for (const child of element.children) {
        if (!observed.has(child)) {
          observer?.observe(child);
          observed.add(child);
        }
      }
    };
    observer?.observe(element);
    observeChildren();
    const mutations =
      typeof MutationObserver === "undefined"
        ? null
        : new MutationObserver(() => {
            observeChildren();
            update();
          });
    mutations?.observe(element, {
      childList: true,
      characterData: true,
      subtree: true,
    });
    return () => {
      element.removeEventListener("scroll", update);
      observer?.disconnect();
      mutations?.disconnect();
    };
  }, [element]);
  return { ref, ...edges };
}
