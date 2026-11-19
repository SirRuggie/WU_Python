import type { ReactNode } from "react";
import "./rosterUi/tokens.css";
import "./CwlPageHeader.css";

// One red-marked page title, help on the title line, and a description below.
// The page's existing controls stay in the actions slot, after the title block.
export default function CwlPageHeader({
  title,
  description,
  help,
  children,
  className = "",
}: {
  /** The page's <h1>. */
  title: ReactNode;
  /** One short line under the title. */
  description?: ReactNode;
  /** A HelpButton. It stays on the title line at every width. */
  help?: ReactNode;
  /** The actions slot: pickers and buttons. A picker drops below the title on phones. */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`cwl-page-header roster-ui ${className}`}>
      <div className="cwl-page-header-title">
        {title}
        {help}
        {description && (
          <p className="cwl-page-header-description">{description}</p>
        )}
      </div>
      {children}
    </div>
  );
}
