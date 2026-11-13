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

/** Lazy tab: approved clan count and the send sheet. Needs Send CWL announcements. */
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
    <section
      className="lazy-announce-card"
      aria-label="Lazy bonus announcement"
    >
      <div>
        <h2>Bonus announcement</h2>
        <p>
          {ready} of {clans.length} clans approved
          {ready === clans.length ? " · Ready for all clans" : ""}
        </p>
      </div>
      <button
        ref={opener}
        type="button"
        disabled={disabled || !ready}
        onClick={() => setOpen(true)}
      >
        Open announcement
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
