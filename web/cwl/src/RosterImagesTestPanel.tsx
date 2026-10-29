import { useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import ChannelCombobox from "./ChannelCombobox";
import { Button } from "./rosterUi/primitives";
import type { AnnouncementChannel } from "./announcements";
import type { ImageData, ImageJob } from "./rosterImagePosting";

export default function RosterImagesTestPanel({
  data,
  channels,
  busy,
  progress,
  error,
  onClose,
  onConfirm,
}: {
  data: ImageData;
  channels: AnnouncementChannel[];
  busy: boolean;
  progress: string;
  error: string;
  onClose: () => void;
  onConfirm: (jobs: ImageJob[], text: string) => void;
}) {
  const [channel, setChannel] = useState("");
  const trigger = useRef(document.activeElement as HTMLElement | null);
  return (
    <ActionPanel
      title="Test all roster images"
      trigger={trigger.current}
      onClose={onClose}
      footer={
        <Button
          variant="primary"
          disabled={busy || !channel || !data.published || !data.clans.length}
          onClick={() =>
            onConfirm(
              data.clans.map((clan) => ({
                clan,
                channel,
                version: data.published!.version,
                operation: "test",
              })),
              `Post a TEST copy of every Main and Lazy clan to #${channels.find((c) => c.id === channel)?.name || channel}? No pings. Nothing is recorded as posted.`,
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
      {progress && <p role="status">{progress}</p>}
      {error && <p role="alert">{error}</p>}
      <p>This channel is used for this test only.</p>
    </ActionPanel>
  );
}
