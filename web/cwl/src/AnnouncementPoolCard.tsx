import { announcementPoolLabel as poolLabel } from "./announcementPoolLabel";
import { createContext, useState, type ReactNode } from "react";
export const AnnouncementMoreContext = createContext<HTMLElement | null>(null);
import { Eye, Pencil, Send } from "lucide-react";
import { Button } from "./rosterUi/primitives";

import type { Pool } from "./api";
export default function AnnouncementPoolCard({
  pool,
  status,
  channel,
  roles,
  dashboardLink,
  enabled,
  changed,
  editable,
  canSend,
  retry,
  sequence,
  tests,
  onPreview,
  onEdit,
  onSend,
}: {
  pool: Pool;
  status: ReactNode;
  channel: string;
  roles: ReactNode;
  dashboardLink: boolean;
  enabled: boolean;
  changed: boolean;
  editable: boolean;
  canSend: boolean;
  retry: boolean;
  sequence?: ReactNode;
  tests?: ReactNode;
  onPreview: () => void;
  onEdit: (trigger: HTMLElement) => void;
  onSend: () => void;
}) {
  const [moreTarget, setMoreTarget] = useState<HTMLDivElement | null>(null);
  return (
    <article className="announcement-pool-card" aria-label={poolLabel(pool)}>
      <h3>{poolLabel(pool)}</h3>
      <div className="announcement-pool-status" role="status">
        {status}
      </div>
      <AnnouncementMoreContext.Provider value={moreTarget}>
        {sequence}
      </AnnouncementMoreContext.Provider>
      {!enabled && <p>Disabled in CWL settings</p>}
      {changed && (
        <p className="announcement-muted">
          Unsaved changes. Save before sending.
        </p>
      )}
      <div className="announcement-card-actions">
        {canSend && (
          <Button icon={Send} onClick={onSend}>
            {retry ? "Review and retry" : "Review and send"}
          </Button>
        )}
      </div>
      <details className="announcement-more">
        <summary>More</summary>
        <div ref={setMoreTarget} />
        <p>
          {channel} · {roles}
        </p>
        <p className="announcement-muted">
          Roster button:{" "}
          {dashboardLink ? "opens My clan assignments ›" : "custom link"}
        </p>

        <div className="announcement-card-actions">
          <Button icon={Eye} onClick={onPreview}>
            Preview
          </Button>
          {editable && (
            <Button
              icon={Pencil}
              onClick={(event) => onEdit(event.currentTarget)}
            >
              Edit
            </Button>
          )}
        </div>
        {tests}
      </details>
    </article>
  );
}
