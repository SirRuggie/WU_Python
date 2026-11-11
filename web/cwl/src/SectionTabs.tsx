import type { HTMLAttributes, ReactNode } from "react";
import useChoiceRail from "./useChoiceRail";
import "./SectionTabs.css";
import "./ChoiceGroupLayout.css";

export default function SectionTabs<T extends string>({
  label,
  items,
  value,
  onChange,
  disabled = false,
  className = "",
  revealSelection = false,
  rootRef,
  ...groupProps
}: {
  label: string;
  items: { id: T; label: ReactNode; disabled?: boolean }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
  revealSelection?: boolean;
  rootRef?: (node: HTMLDivElement | null) => void;
} & Omit<HTMLAttributes<HTMLDivElement>, "children" | "onChange">) {
  const { ref, fadeProps } = useChoiceRail<HTMLDivElement>(
    `${value}\0${items.map((item) => item.id).join("\0")}`,
    revealSelection,
    rootRef,
  );
  return (
    <div
      {...groupProps}
      {...fadeProps}
      ref={ref}
      className={`section-tabs has-horizontal-fades ${className}`}
      role="group"
      aria-label={label}
    >
      {items.map((item) => (
        <button
          type="button"
          key={item.id}
          aria-pressed={value === item.id}
          disabled={disabled || item.disabled}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
