import { useLayoutEffect, useState, type RefObject } from "react";

/** A topbar group is useful only when it adds context to the page label. */
export function pageBreadcrumb(section: string | undefined, label: string) {
  return section && section !== label ? section : "";
}

/** Follow the rendered page heading, including lazy and conditional pages. */
export function observePageHeading(
  main: HTMLElement,
  topbar: HTMLElement | null,
  onVisibility: (visible: boolean) => void,
) {
  let active = true;
  let heading: HTMLHeadingElement | null = null;
  let intersection: IntersectionObserver | null = null;
  let generation = 0;
  const shell = topbar?.closest<HTMLElement>(".shell");
  const syncTopbarHeight = () => {
    if (!topbar || !shell) return;
    const height =
      getComputedStyle(topbar).position === "sticky"
        ? topbar.getBoundingClientRect().height
        : 0;
    const value = `${height}px`;
    if (shell.style.getPropertyValue("--wu-topbar-h") !== value)
      shell.style.setProperty("--wu-topbar-h", value);
  };

  const topInset = () =>
    Math.max(0, topbar?.getBoundingClientRect().bottom ?? 0);
  const findHeading = () =>
    [...main.querySelectorAll("h1")].find((candidate) => {
      if (
        candidate.closest(
          '[hidden], [aria-hidden="true"], dialog, [role="dialog"]',
        )
      )
        return false;
      const rect = candidate.getBoundingClientRect();
      return rect.width > 0 && rect.height > 0;
    }) ?? null;

  const bindHeading = (force = false) => {
    if (!active) return;
    if (force) syncTopbarHeight();
    const next = findHeading();
    if (!force && next === heading) return;
    intersection?.disconnect();
    const boundGeneration = ++generation;
    intersection = null;
    heading = next;
    // A loading/error page with no h1 still retains its topbar title.
    if (!heading) {
      onVisibility(false);
      return;
    }
    const current = heading;
    const inset = topInset();
    const rect = current.getBoundingClientRect();
    onVisibility(rect.bottom > inset && rect.top < window.innerHeight);
    if (typeof IntersectionObserver === "undefined") return;
    intersection = new IntersectionObserver(
      (entries) => {
        if (!active || heading !== current || generation !== boundGeneration)
          return;
        const entry = entries.find((item) => item.target === current);
        if (entry) onVisibility(entry.isIntersecting);
      },
      { rootMargin: `-${inset}px 0px 0px 0px`, threshold: 0 },
    );
    intersection.observe(current);
  };

  bindHeading(true);
  const mutations = new MutationObserver(() => bindHeading());
  mutations.observe(main, {
    childList: true,
    subtree: true,
    attributes: true,
    attributeFilter: ["hidden", "aria-hidden", "class"],
  });
  const resize =
    typeof ResizeObserver === "undefined"
      ? null
      : new ResizeObserver(() => bindHeading(true));
  if (topbar) resize?.observe(topbar);

  return () => {
    active = false;
    intersection?.disconnect();
    mutations.disconnect();
    resize?.disconnect();
  };
}

export function usePageHeadingVisibility(
  main: RefObject<HTMLElement | null>,
  topbar: RefObject<HTMLElement | null>,
  routeKey: string,
  signedIn: boolean,
) {
  // Hide the redundant phone title on the first paint until layout is known.
  const [visible, setVisible] = useState(true);
  useLayoutEffect(() => {
    if (!signedIn || !main.current) return;
    return observePageHeading(main.current, topbar.current, setVisible);
  }, [main, topbar, routeKey, signedIn]);
  return visible;
}
