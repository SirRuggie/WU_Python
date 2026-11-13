import { useState, type ReactNode } from "react";

export default function MessagePreview({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState(false);
  return (
    <details
      className="reminder-disclosure"
      onToggle={(event) => setOpen(event.currentTarget.open)}
    >
      <summary>Discord preview</summary>
      {open && children}
    </details>
  );
}
