import HelpButton from "./HelpButton";
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

/** The page's "?" help; opens the shared help side sheet. */
export default function StrikeHelp({
  limit = DEFAULT_STRIKE_LIMIT,
}: {
  limit?: number;
}) {
  return (
    <HelpButton title="How strikes work" className="strike-help-panel">
      <StrikeHelpText limit={limit} />
    </HelpButton>
  );
}
