import { announcementPoolLabel as poolLabel } from "./announcementPoolLabel";
import { useState, type ReactNode } from "react";
import { Save, Send } from "lucide-react";
import ActionPanel from "./ActionPanel";
import ChannelCombobox from "./ChannelCombobox";
import { Button, Input } from "./rosterUi/primitives";
import { type AnnouncementChannel } from "./announcements";
import type { Pool } from "./api";
import type { AnnouncementDraft } from "./announcementDrafts";
export default function AnnouncementEditor({
  pool,
  trigger,
  draft,
  channels,
  editable,
  locked,
  busy,
  changed,
  testAllowed,
  testChannel,
  testUrl,
  notice,
  onDraft,
  onClose,
  onSave,
  onTestChannel,
  onTest,
  fullTest,
}: {
  fullTest?: ReactNode;
  pool: Pool;
  trigger: HTMLElement | null;
  draft: AnnouncementDraft;
  channels: AnnouncementChannel[];
  editable: boolean;
  locked: boolean;
  busy: boolean;
  changed: boolean;
  testAllowed: boolean;
  testChannel: string;
  testUrl: string;
  notice: ReactNode;
  onDraft: (update: Partial<AnnouncementDraft>) => void;
  onClose: () => void;
  onSave: () => void;
  onTestChannel: (value: string) => void;
  onTest: () => void;
}) {
  const [changeLink, setChangeLink] = useState(false);
  return (
    <ActionPanel
      title={`${poolLabel(pool)} message`}
      trigger={trigger}
      onClose={onClose}
      busy={busy}
      className="announcement-edit-panel"
      footer={
        <Button
          icon={Save}
          variant="primary"
          disabled={!editable || !changed}
          onClick={onSave}
        >
          Save message
        </Button>
      }
    >
      <div className="announcement-editor-body">
        {notice}
        {locked && (
          <p>
            This message is locked because it has been sent, is in progress, or
            needs delivery review.
          </p>
        )}
        <ChannelCombobox
          label={`${poolLabel(pool)} destination`}
          channels={channels}
          value={draft.channel_id}
          disabled={!editable}
          onChange={(value) => onDraft({ channel_id: value })}
        />
        <label>
          Message
          <textarea
            rows={6}
            maxLength={4000}
            value={draft.body}
            disabled={!editable}
            onChange={(event) => onDraft({ body: event.target.value })}
          />
        </label>
        {changeLink ? (
          <Input
            label="Roster button link"
            type="url"
            value={draft.roster_url}
            disabled={!editable}
            onChange={(event) => onDraft({ roster_url: event.target.value })}
          />
        ) : (
          <div>
            <span>Roster button link</span>
            <p className="announcement-link">
              {draft.roster_url || "No link saved"}
            </p>
            <Button disabled={!editable} onClick={() => setChangeLink(true)}>
              Change link
            </Button>
          </div>
        )}
        {changed && (
          <p className="announcement-muted">
            Unsaved changes. Saving does not send a Discord message.
          </p>
        )}
        <details className="announcement-test">
          <summary>Send test · no pings</summary>
          <ChannelCombobox
            label="Test channel"
            channels={channels}
            value={testChannel}
            disabled={!testAllowed}
            onChange={onTestChannel}
          />
          <Button
            icon={Send}
            disabled={!testAllowed || !testChannel}
            onClick={onTest}
          >
            Send test
          </Button>
          {testUrl && (
            <a href={testUrl} target="_blank" rel="noopener noreferrer">
              View test in Discord ↗
            </a>
          )}
        </details>
        {fullTest}
      </div>
    </ActionPanel>
  );
}
