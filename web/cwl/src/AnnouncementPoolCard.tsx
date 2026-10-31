import { announcementPoolLabel as poolLabel } from "./announcementPoolLabel";
import type { ReactNode } from "react";
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
  onPreview: () => void;
  onEdit: (trigger: HTMLElement) => void;
  onSend: () => void;
}) {
  return (
    <article className="announcement-pool-card" aria-label={poolLabel(pool)}>
      <h3>{poolLabel(pool)}</h3>
      <div className="announcement-pool-status" role="status">
        {status}
      </div>
      {sequence}
      <p>
        {channel} · {roles}
      </p>
      <p className="announcement-muted">
        Roster button:{" "}
        {dashboardLink ? "opens My clan assignments ›" : "custom link"}
      </p>
      {!enabled && <p>Disabled in CWL settings</p>}
      {changed && (
        <p className="announcement-muted">
          Unsaved changes. Save before sending.
        </p>
      )}
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
        {canSend && (
          <Button icon={Send} onClick={onSend}>
            {retry ? "Retry" : "Send"}
          </Button>
        )}
      </div>
    </article>
  );
}
