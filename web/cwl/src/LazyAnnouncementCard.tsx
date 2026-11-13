import { useRef, useState } from "react";
import { useDashboardPermission } from "./DashboardPermissions";
import LazyAnnouncementSheet from "./LazyAnnouncementSheet";
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

/** Lazy tab: one compact row with the approved clan count and Open. Needs Send CWL announcements. */
export default function LazyAnnouncementCard({
  seasonId,
  clans,
  clanTag,
  archived,
  disabled,
  onSent,
}: Props) {
  const canSend = useDashboardPermission("cwl_send");
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);
  if (!canSend || !clans.length) return null;
  const ready = readyCount(clans);
  return (
    <section className="lazy-announce-row" aria-label="Lazy bonus announcement">
      <p>
        Announcement ·{" "}
        <strong>
          {ready} of {clans.length}
        </strong>{" "}
        approved
      </p>
      <button
        ref={opener}
        type="button"
        aria-label="Open bonus announcement"
        disabled={disabled || !ready}
        onClick={() => setOpen(true)}
      >
        Open
      </button>
      {open && (
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
          trigger={opener.current}
          onClose={() => setOpen(false)}
          onSent={onSent}
        />
      )}
    </section>
  );
}
