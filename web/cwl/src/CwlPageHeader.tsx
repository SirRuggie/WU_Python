import type { ReactNode } from "react";
import PageEyebrow from "./PageEyebrow";
import "./rosterUi/tokens.css";
import "./CwlPageHeader.css";

// The one page header: sidebar-group eyebrow, red-marked title, optional ? help
// on the title line, an optional one-line description, then the page's own
// controls (season picker, refresh, …) in the actions slot.
export default function CwlPageHeader({
  title,
  description,
  help,
  eyebrow = true,
  children,
  className = "",
}: {
  /** The page's <h1>. */
  title: ReactNode;
  /** One short line under the title. */
  description?: ReactNode;
  /** A HelpButton. It stays on the title line at every width. */
  help?: ReactNode;
  /** False only for Home, whose greeting has no sidebar group. */
  eyebrow?: boolean;
  /** The actions slot: pickers and buttons. A picker drops below the title on phones. */
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`page-head cwl-page-header roster-ui ${className}`}>
      <div className="cwl-page-header-title">
        {eyebrow && <PageEyebrow />}
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
