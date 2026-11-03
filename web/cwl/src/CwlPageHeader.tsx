import type { ReactNode } from "react";
import "./rosterUi/tokens.css";
import "./CwlPageHeader.css";

// The same compact title/season/action row; callers keep their existing controls.
export default function CwlPageHeader({
  title,
  children,
  className = "",
}: {
  title: ReactNode;
  children?: ReactNode;
  className?: string;
}) {
  return (
    <div className={`page-head cwl-page-header roster-ui ${className}`}>
      <div className="cwl-page-header-title">{title}</div>
      {children}
    </div>
  );
}
