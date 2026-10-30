import { useState } from "react";
import ActionPanel from "./ActionPanel";
import { DEFAULT_STRIKE_LIMIT, strikeHelpLines } from "./strikeHelp";
import "./StrikeHelp.css";

export function StrikeHelpText({
  limit = DEFAULT_STRIKE_LIMIT,
}: {
  limit?: number;
}) {
  return (
    <ul className="strike-help-copy">
      {strikeHelpLines(limit).map((line, index) => (
        <li key={index}>
          {line.map((part, partIndex) =>
            part.strong ? (
              <strong key={partIndex}>{part.text}</strong>
            ) : (
              part.text
            ),
          )}
        </li>
      ))}
    </ul>
  );
}

export default function StrikeHelp({
  limit = DEFAULT_STRIKE_LIMIT,
}: {
  limit?: number;
}) {
  const [trigger, setTrigger] = useState<HTMLButtonElement | null>(null);
  return (
    <>
      <button
        type="button"
        className="strike-help-trigger"
        onClick={(event) => setTrigger(event.currentTarget)}
      >
        How strikes work
      </button>
      {trigger && (
        <ActionPanel
          title="How strikes work"
          className="strike-help-panel"
          trigger={trigger}
          onClose={() => setTrigger(null)}
        >
          <StrikeHelpText limit={limit} />
        </ActionPanel>
      )}
    </>
  );
}
