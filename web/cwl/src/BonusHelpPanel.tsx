import { useRef, useState } from "react";
import { CircleHelp } from "lucide-react";
import ActionPanel from "./ActionPanel";
import "./BonusHelpPanel.css";

export default function BonusHelpPanel() {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);

  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="bonus-help-trigger"
        aria-label="How bonuses work"
        title="How bonuses work"
        onClick={() => setOpen(true)}
      >
        <CircleHelp size={18} aria-hidden="true" />
      </button>
      {open && (
        <ActionPanel
          title="How bonuses work"
          variant="side"
          className="bonus-help-panel roster-ui"
          trigger={trigger.current}
          onClose={() => setOpen(false)}
        >
          <h3>Bonus count</h3>
          <p>It comes from the CWL league, plus 1 for each war win.</p>
          <h3>Who qualifies</h3>
          <p>
            Main: the minimum attacks in the Rules step. Lazy: 4+ attacks, or 3+
            attacks and 8+ stars. One bonus per account each month.
          </p>
          <h3>Infractions (Lazy)</h3>
          <p>
            Missed sync, Lingering or Left family removes the account this
            month. A staff reason can put it back.
          </p>
          <h3>Sit-out after a win (Lazy)</h3>
          <p>
            A winner sits out for a set number of months. Each clan sets its
            number in Settings. Default 3. Example: October win, 3 months → can
            win again in February.
          </p>
          <h3>Draw</h3>
          <p>
            Winners are drawn at random. FWA Rep accounts selected in Settings
            have 2× the chance in Lazy.
          </p>
        </ActionPanel>
      )}
    </>
  );
}
