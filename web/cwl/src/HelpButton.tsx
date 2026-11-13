import { useRef, useState, type ReactNode } from "react";
import { CircleHelp } from "lucide-react";
import ActionPanel from "./ActionPanel";
import "./HelpButton.css";

/**
 * The one page help pattern: a 44px ? next to the page title that opens a
 * side sheet. Use it through CwlPageHeader's `help` slot.
 */
export default function HelpButton({
  title,
  className = "",
  children,
}: {
  /** Sheet title and the button's accessible name, e.g. "How bonuses work". */
  title: string;
  className?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const trigger = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="page-help-trigger"
        aria-label={title}
        title={title}
        onClick={() => setOpen(true)}
      >
        <CircleHelp size={20} aria-hidden="true" />
      </button>
      {open && (
        <ActionPanel
          title={title}
          variant="side"
          className={`page-help-panel roster-ui ${className}`}
          trigger={trigger.current}
          onClose={() => setOpen(false)}
        >
          {children}
        </ActionPanel>
      )}
    </>
  );
}
