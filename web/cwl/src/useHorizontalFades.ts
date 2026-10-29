import { useEffect, useRef, useState } from "react";

export function horizontalFadeState(
  element: Pick<HTMLElement, "scrollLeft" | "scrollWidth" | "clientWidth">,
) {
  return {
    left: element.scrollLeft > 1,
    right: element.scrollLeft + element.clientWidth < element.scrollWidth - 1,
  };
}

export function useHorizontalFades<T extends HTMLElement>() {
  const ref = useRef<T>(null);
  const [edges, setEdges] = useState({ left: false, right: false });
  useEffect(() => {
    const element = ref.current;
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
    observer?.observe(element);
    for (const child of element.children) observer?.observe(child);
    return () => {
      element.removeEventListener("scroll", update);
      observer?.disconnect();
    };
  });
  return { ref, ...edges };
}
