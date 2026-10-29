import {
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
} from "react";
import type { LucideIcon } from "lucide-react";
import "./tokens.css";
import "./primitives.css";

export type ButtonVariant = "primary" | "secondary" | "danger" | "icon";

export function Button({
  variant = "secondary",
  icon: Icon,
  label,
  className = "",
  type = "button",
  children,
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: ButtonVariant;
  icon?: LucideIcon;
  label?: string;
}) {
  return (
    <button
      {...props}
      type={type}
      className={`roster-ui roster-ui-button is-${variant}${className ? ` ${className}` : ""}`}
      aria-label={label || props["aria-label"]}
    >
      {Icon && <Icon className="roster-ui-icon" aria-hidden="true" />}
      {children && <span>{children}</span>}
    </button>
  );
}

export type StatusTone = "neutral" | "success" | "warning" | "danger" | "info";

export function StatusPill({
  tone = "neutral",
  children,
  className = "",
}: {
  tone?: StatusTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={`roster-ui roster-ui-status is-${tone}${className ? ` ${className}` : ""}`}
    >
      {children}
    </span>
  );
}

export function ProgressBar({
  value,
  max = 100,
  label,
  valueText,
  className = "",
  decorative = false,
}: {
  value: number;
  max?: number;
  label: string;
  valueText?: string;
  decorative?: boolean;
  className?: string;
}) {
  const boundedMax = Number.isFinite(max) && max > 0 ? max : 100;
  const boundedValue = Number.isFinite(value)
    ? Math.max(0, Math.min(value, boundedMax))
    : 0;
  const percent = (boundedValue / boundedMax) * 100;
  const Element = decorative ? "span" : "div";
  return (
    <Element
      className={`roster-ui roster-ui-progress${className ? ` ${className}` : ""}`}
      role={decorative ? undefined : "progressbar"}
      aria-hidden={decorative || undefined}
      aria-label={decorative ? undefined : label}
      aria-valuemin={decorative ? undefined : 0}
      aria-valuemax={decorative ? undefined : boundedMax}
      aria-valuenow={decorative ? undefined : boundedValue}
      aria-valuetext={decorative ? undefined : valueText}
    >
      <span className="roster-ui-progress-track">
        <span style={{ width: `${percent}%` }} />
      </span>
    </Element>
  );
}

export function Chip({
  children,
  tone = "neutral",
  onRemove,
  removeLabel = "Remove",
}: {
  children: ReactNode;
  tone?: StatusTone;
  onRemove?: () => void;
  removeLabel?: string;
}) {
  return (
    <span className={`roster-ui roster-ui-chip is-${tone}`}>
      <span>{children}</span>
      {onRemove && (
        <button type="button" onClick={onRemove} aria-label={removeLabel}>
          ×
        </button>
      )}
    </span>
  );
}

export function Input({
  icon: Icon,
  label,
  hint,
  error,
  id,
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement> & {
  icon?: LucideIcon;
  label?: string;
  hint?: ReactNode;
  error?: string;
}) {
  const generatedId = useId();
  const inputId = id || generatedId;
  const hintId = hint ? `${inputId}-hint` : undefined;
  const errorId = error ? `${inputId}-error` : undefined;
  const describedBy =
    [props["aria-describedby"], hintId, errorId].filter(Boolean).join(" ") ||
    undefined;
  return (
    <div
      className={`roster-ui roster-ui-input${error ? " has-error" : ""}${className ? ` ${className}` : ""}`}
    >
      {label && <label htmlFor={inputId}>{label}</label>}
      <div className={`roster-ui-input-control${Icon ? " has-icon" : ""}`}>
        {Icon && <Icon className="roster-ui-input-icon" aria-hidden="true" />}
        <input
          {...props}
          id={inputId}
          aria-invalid={error ? true : props["aria-invalid"]}
          aria-describedby={describedBy}
        />
      </div>
      {hint && <small id={hintId}>{hint}</small>}
      {error && (
        <small id={errorId} className="roster-ui-input-error">
          {error}
        </small>
      )}
    </div>
  );
}
