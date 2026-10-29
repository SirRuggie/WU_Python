import { useEffect, useRef, type RefObject } from "react";

/** Commit a phone rail swipe once it settles; explicit selection scrolls only horizontally. */
export default function useCompareRail(
  rail: RefObject<HTMLDivElement | null>,
  tags: string[],
  selected: string | undefined,
  onSelect: (tag: string) => void,
) {
  const latest = useRef({ tags, selected, onSelect });
  latest.current = { tags, selected, onSelect };
  const destination = useRef<string | null>(null);
  const key = tags.join("|");
  useEffect(() => {
    const element = rail.current;
    if (!element) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const settle = () => {
      clearTimeout(timer);
      const cards = [...element.children] as HTMLElement[];
      const left = element.getBoundingClientRect().left;
      const nearest = cards.reduce(
        (best, card, index) =>
          Math.abs(card.getBoundingClientRect().left - left) <
          Math.abs(cards[best].getBoundingClientRect().left - left)
            ? index
            : best,
        0,
      );
      const tag = latest.current.tags[nearest];
      if (destination.current && tag !== destination.current) return;
      destination.current = null;
      if (tag && tag !== latest.current.selected) latest.current.onSelect(tag);
    };
    const scroll = () => {
      clearTimeout(timer);
      timer = setTimeout(settle, 120);
    };
    const userScroll = () => {
      destination.current = null;
    };
    element.addEventListener("scroll", scroll);
    element.addEventListener("scrollend", settle);
    element.addEventListener("pointerdown", userScroll);
    element.addEventListener("touchstart", userScroll);
    return () => {
      clearTimeout(timer);
      destination.current = null;
      element.removeEventListener("scroll", scroll);
      element.removeEventListener("scrollend", settle);
      element.removeEventListener("pointerdown", userScroll);
      element.removeEventListener("touchstart", userScroll);
    };
  }, [rail, key]);
  useEffect(() => {
    const element = rail.current;
    const index = tags.indexOf(selected || "");
    const card = element?.children[index] as HTMLElement | undefined;
    if (!element || !card || !element.getBoundingClientRect().width) return;
    const offset =
      card.getBoundingClientRect().left - element.getBoundingClientRect().left;
    if (Math.abs(offset) < 1) return;
    destination.current = selected || null;
    element.scrollTo({
      left: element.scrollLeft + offset,
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  }, [rail, selected, key]);
}
