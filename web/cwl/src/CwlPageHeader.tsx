import type { ReactNode } from "react";
import PageEyebrow from "./PageEyebrow";
import "./rosterUi/tokens.css";
import "./CwlPageHeader.css";

// The shared page header: sidebar-group eyebrow, title, optional ? help on the
// title line, then the page's own controls (season picker, refresh, …).
export default function CwlPageHeader({
  title,
  help,
  children,
  className = "",
}: {
  title: ReactNode;
  /** A HelpButton. It stays on the title line at every width. */
  help?: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`page-head cwl-page-header roster-ui ${className}`}>
      <div className="cwl-page-header-title">
        <PageEyebrow />
        {title}
        {help}
      </div>
      {children}
    </div>
  );
}
