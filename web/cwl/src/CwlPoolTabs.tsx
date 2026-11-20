import { useState } from "react";
import type { Pool } from "./api";
import SectionTabs from "./SectionTabs";
import "./CwlPoolTabs.css";
export function useCwlPool() {
  const [pool, setPool] = useState<Pool>(() => {
    try {
      return localStorage.getItem("wu-staff-cwl-pool") === "lazy"
        ? "lazy"
        : "main";
    } catch {
      return "main";
    }
  });
  return [
    pool,
    (next: Pool) => {
      setPool(next);
      try {
        localStorage.setItem("wu-staff-cwl-pool", next);
      } catch {}
    },
  ] as const;
}
export default function CwlPoolTabs({
  value,
  onChange,
  disabled = false,
  compactLabels = false,
  id,
}: {
  value: Pool;
  onChange: (pool: Pool) => void;
  disabled?: boolean;
  compactLabels?: boolean;
  id?: string;
}) {
  return (
    <SectionTabs
      mode="segmented"
      id={id}
      className="cwl-pool-tabs section-tabs--flow"
      label="CWL group"
      items={[
        { id: "main", label: compactLabels ? "Main" : "Main CWL" },
        { id: "lazy", label: compactLabels ? "Lazy" : "Lazy CWL" },
      ]}
      value={value}
      onChange={onChange}
      disabled={disabled}
      revealSelection
    />
  );
}
