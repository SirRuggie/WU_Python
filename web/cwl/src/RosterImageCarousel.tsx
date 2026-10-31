import { useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "./rosterUi/primitives";
import useCompareRail from "./useCompareRail";
import "./RosterImageCarousel.css";
export type RosterImageClan = {
  tag: string;
  name: string;
  pool: string;
  count: number;
  pages: number;
};
export default function RosterImageCarousel({
  clans,
  selected,
  version,
  path,
  disabled,
  onSelect,
  onReady,
}: {
  clans: RosterImageClan[];
  selected: string;
  version: number;
  path: string;
  disabled: boolean;
  onSelect: (tag: string) => void;
  onReady: (ready: boolean) => void;
}) {
  const rail = useRef<HTMLDivElement>(null);
  const [jump, setJump] = useState(false);
  const [settled, setSettled] = useState(true);
  const [loaded, setLoaded] = useState<Record<string, boolean>>({});
  const [failed, setFailed] = useState<Record<string, boolean>>({});
  const index = Math.max(
    0,
    clans.findIndex((clan) => clan.tag === selected),
  );
  const current = clans[index];
  const choose = (tag: string) => {
    if (!disabled) {
      if (tag !== selected) onSelect(tag);
      setJump(false);
    }
  };
  useCompareRail(
    rail,
    clans.map((clan) => clan.tag),
    selected,
    choose,
  );
  useEffect(() => {
    const element = rail.current;
    if (!element) return;
    const update = () => {
      const bounds = element.getBoundingClientRect();
      const card = element.children[index] as HTMLElement | undefined;
      setSettled(
        !bounds.width ||
          (!!card &&
            Math.abs(card.getBoundingClientRect().left - bounds.left) < 2),
      );
    };
    update();
    element.addEventListener("scroll", update);
    element.addEventListener("scrollend", update);
    return () => {
      element.removeEventListener("scroll", update);
      element.removeEventListener("scrollend", update);
    };
  }, [index, selected]);
  const pageKey = (tag: string, page: number) => `${version}:${tag}:${page}`;
  const ready =
    !!current &&
    Array.from(
      { length: current.pages },
      (_, page) =>
        loaded[pageKey(current.tag, page)] &&
        !failed[pageKey(current.tag, page)],
    ).every(Boolean);
  useEffect(
    () => onReady(ready && settled),
    [ready, settled, selected, onReady],
  );
  useEffect(() => {
    if (disabled) setJump(false);
  }, [disabled]);
  if (!current) return null;
  return (
    <div className="roster-image-carousel">
      <div className="image-carousel-position" aria-live="polite">
        Clan {index + 1} of {clans.length} ·{" "}
        <button
          type="button"
          aria-expanded={jump}
          disabled={disabled}
          onClick={() => setJump((value) => !value)}
        >
          {current.name}
        </button>{" "}
        · {current.count} players
      </div>
      {jump && (
        <ul className="image-carousel-jump" aria-label="Jump to clan">
          {clans.map((clan) => (
            <li key={clan.tag}>
              <button
                type="button"
                onClick={() => choose(clan.tag)}
                aria-current={clan.tag === selected ? "true" : undefined}
              >
                {clan.name} · {clan.count} players
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="image-carousel-controls">
        <Button
          aria-label="Previous clan"
          icon={ChevronLeft}
          disabled={disabled || index === 0}
          onClick={() => choose(clans[index - 1].tag)}
        >
          Previous clan
        </Button>
        <Button
          aria-label="Next clan"
          icon={ChevronRight}
          disabled={disabled || index === clans.length - 1}
          onClick={() => choose(clans[index + 1].tag)}
        >
          Next clan
        </Button>
      </div>
      <div
        className="image-carousel-rail"
        ref={rail}
        tabIndex={0}
        role="region"
        aria-label="Clan roster images"
        aria-disabled={disabled}
        onKeyDown={(event) => {
          if (
            disabled ||
            event.target !== event.currentTarget ||
            !["ArrowLeft", "ArrowRight"].includes(event.key)
          )
            return;
          event.preventDefault();
          choose(
            clans[
              Math.max(
                0,
                Math.min(
                  clans.length - 1,
                  index + (event.key === "ArrowRight" ? 1 : -1),
                ),
              )
            ].tag,
          );
        }}
      >
        {clans.map((clan, at) => (
          <article
            key={clan.tag}
            aria-label={`${clan.name} roster`}
            aria-hidden={at !== index}
            className="image-carousel-card"
          >
            <h4>
              {clan.name} · {clan.count} players
            </h4>
            {Math.abs(at - index) <= 1 ? (
              Array.from({ length: clan.pages }, (_, page) => {
                const src = `/api/cwl${path}/${encodeURIComponent(clan.tag)}.png?version=${version}&page=${page + 1}`;
                const key = pageKey(clan.tag, page);
                return (
                  <div key={key}>
                    <img
                      src={src}
                      alt={`${clan.name} finalized roster, page ${page + 1}`}
                      className="clan-roster-image"
                      onLoad={() =>
                        setLoaded((old) => ({ ...old, [key]: true }))
                      }
                      onError={() =>
                        setFailed((old) => ({ ...old, [key]: true }))
                      }
                    />
                    {failed[key] && (
                      <p role={at === index ? "alert" : undefined}>
                        Image unavailable. Refresh images to try again.
                      </p>
                    )}
                    <a
                      className="button"
                      tabIndex={at === index ? 0 : -1}
                      href={src}
                      download={`roster-${clan.tag.slice(1)}-${page + 1}.png`}
                    >
                      Download{clan.pages > 1 ? ` page ${page + 1}` : " image"}
                    </a>
                  </div>
                );
              })
            ) : (
              <p>Swipe to load this clan’s images.</p>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
