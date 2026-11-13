import { useRef, useState } from "react";
import { useDashboardPermission } from "./DashboardPermissions";
import LazyAnnouncementSheet from "./LazyAnnouncementSheet";
import LazyInfractionsSheet from "./LazyInfractionsSheet";
import type { BonusStatusClan } from "./bonusStatus";
import { readyCount } from "./lazyAnnouncement";
import "./LazyAnnouncement.css";

type Props = {
  seasonId: string;
  clans: BonusStatusClan[];
  clanTag: string;
  archived: boolean;
  disabled: boolean;
  onSent: () => void;
};

/**
 * Lazy tab: "Announcements" with one compact row per post.
 * Bonus winners needs Send CWL announcements. Infractions opens for bonus
 * staff as a list; its Send also needs Send CWL announcements.
 */
export default function LazyAnnouncementCard({
  seasonId,
  clans,
  clanTag,
  archived,
  disabled,
  onSent,
}: Props) {
  const canSend = useDashboardPermission("cwl_send");
  const [open, setOpen] = useState<"" | "bonus" | "infractions">("");
  const bonusOpener = useRef<HTMLButtonElement | null>(null);
  const infractionsOpener = useRef<HTMLButtonElement | null>(null);
  if (!clans.length) return null;
  const ready = readyCount(clans);
  return (
    <section className="lazy-announce-group" aria-label="Lazy announcements">
      <h3 className="lazy-announce-heading">Announcements</h3>
      <div className="lazy-announce-rows">
        {canSend && (
          <div className="lazy-announce-row">
            <span className="lazy-announce-dot is-bonus" aria-hidden="true" />
            <p>
              Bonus winners ·{" "}
              <strong>
                {ready} of {clans.length}
              </strong>{" "}
              approved
            </p>
            <button
              ref={bonusOpener}
              type="button"
              aria-label="Open bonus announcement"
              disabled={disabled || !ready}
              onClick={() => setOpen("bonus")}
            >
              Open
            </button>
          </div>
        )}
        <div className="lazy-announce-row">
          <span
            className="lazy-announce-dot is-infractions"
            aria-hidden="true"
          />
          <p>Infractions</p>
          <button
            ref={infractionsOpener}
            type="button"
            aria-label="Open infractions"
            disabled={disabled}
            onClick={() => setOpen("infractions")}
          >
            Open
          </button>
        </div>
      </div>
      {open === "bonus" && (
        <LazyAnnouncementSheet
          seasonId={seasonId}
          clans={clans.filter(
            (c) => c.draw_state === "approved" || c.draw_state === "sent",
          )}
          initialClan={
            clans.some(
              (c) =>
                c.tag === clanTag &&
                (c.draw_state === "approved" || c.draw_state === "sent"),
            )
              ? clanTag
              : ""
          }
          archived={archived}
          trigger={bonusOpener.current}
          onClose={() => setOpen("")}
          onSent={onSent}
        />
      )}
      {open === "infractions" && (
        <LazyInfractionsSheet
          seasonId={seasonId}
          archived={archived}
          canSend={canSend}
          trigger={infractionsOpener.current}
          onClose={() => setOpen("")}
        />
      )}
    </section>
  );
}
