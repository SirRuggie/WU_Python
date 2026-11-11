import type { ReactNode } from "react";
import useChoiceRail from "./useChoiceRail";
import "./FilterChips.css";
import "./ChoiceGroupLayout.css";
export default function FilterChips<T extends string | number>({
  label,
  value,
  options,
  onChange,
  disabled = false,
  className = "",
  variant = "default",
  role,
  revealSelection = false,
}: {
  label: string;
  value: T | null;
  options: {
    value: T;
    label: ReactNode;
    count?: number | string;
    ariaLabel?: string;
  }[];
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
  variant?: "default" | "pill";
  role?: "group";
  revealSelection?: boolean;
}) {
  const { ref, fadeProps } = useChoiceRail<HTMLDivElement>(
    `${value}\0${options.map((option) => option.value).join("\0")}`,
    revealSelection,
  );
  return (
    <div
      {...fadeProps}
      ref={ref}
      className={
        variant === "pill"
          ? `filter-chips has-horizontal-fades ${className} filter-chips--pill`
          : `filter-chips has-horizontal-fades ${className}`
      }
      role={role}
      aria-label={label}
    >
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          aria-label={option.ariaLabel}
          aria-pressed={value === option.value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
        >
          {option.label}
          {option.count !== undefined && (
            <>
              {" "}
              <small>{option.count}</small>
            </>
          )}
        </button>
      ))}
    </div>
  );
}
