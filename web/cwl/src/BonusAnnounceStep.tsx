import BonusAnnouncement from "./BonusAnnouncement";
import type { SavedDraw } from "./bonusRaffle";

type Props = {
  gate: string;
  draw: SavedDraw | undefined;
  disabled: boolean;
  onSend: (channel: string, retry?: boolean) => void;
};

/** Step 5: channel, check box, Send announcement. The medals are given in Clash. */
export default function BonusAnnounceStep({
  gate,
  draw,
  disabled,
  onSend,
}: Props) {
  if (!draw || gate) return <p className="bonus-action-blocker">{gate}</p>;
  return (
    <>
      <p className="bonus-step-note">Give the medals in Clash.</p>
      <BonusAnnouncement
        key={draw.id}
        draw={draw}
        disabled={disabled}
        onSend={onSend}
      />
    </>
  );
}
