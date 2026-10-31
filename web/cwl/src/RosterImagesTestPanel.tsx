import useAnnouncementTestChannel from "./useAnnouncementTestChannel";
import TestChannelDefault from "./TestChannelDefault";
import { useRef } from "react";
import ActionPanel from "./ActionPanel";
import ChannelCombobox from "./ChannelCombobox";
import { Button } from "./rosterUi/primitives";
import type { AnnouncementChannel } from "./announcements";
import type { ImageData, ImageJob } from "./rosterImagePosting";

export default function RosterImagesTestPanel({
  canSend,
  data,
  channels,
  busy,
  progress,
  error,
  onClose,
  onConfirm,
}: {
  canSend: boolean;
  data: ImageData;
  channels: AnnouncementChannel[];
  busy: boolean;
  progress: string;
  error: string;
  onClose: () => void;
  onConfirm: (
    jobs: ImageJob[],
    text: string,
    beforeSend?: () => Promise<void>,
  ) => void;
}) {
  const destination = useAnnouncementTestChannel(canSend);
  const { channel, setChannel } = destination;
  const trigger = useRef(document.activeElement as HTMLElement | null);
  return (
    <ActionPanel
      title="Test all roster images"
      trigger={trigger.current}
      onClose={onClose}
      footer={
        <Button
          variant="primary"
          disabled={!canSend || busy || !channel || !data.published || !data.clans.length}
          onClick={() =>
            onConfirm(
              data.clans.map((clan) => ({
                clan,
                channel,
                version: data.published!.version,
                operation: "test",
              })),
              `Post a TEST copy of every Main and Lazy clan to #${channels.find((c) => c.id === channel)?.name || channel}? No pings. Nothing is recorded as posted.`,
              destination.saveDefault,
            )
          }
        >
          Review test
        </Button>
      }
    >
      <ChannelCombobox
        label="Test channel"
        channels={channels}
        value={channel}
        disabled={busy}
        onChange={setChannel}
      />
      <TestChannelDefault
        checked={destination.makeDefault}
        disabled={busy || !canSend}
        error={destination.error}
        onChange={destination.setMakeDefault}
        onReload={destination.reload}
      />
      {progress && <p role="status">{progress}</p>}
      {error && <p role="alert">{error}</p>}
      <p>
        This choice applies only to this test unless you make it the default.
      </p>
    </ActionPanel>
  );
}
