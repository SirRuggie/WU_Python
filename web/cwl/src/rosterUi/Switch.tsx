import "./tokens.css";
import "./Switch.css";

type Props = {
  checked: boolean;
  onChange: (next: boolean) => void;
  disabled?: boolean;
  /** A problem never shows a green switch. */
  problem?: boolean;
  /** Visible name shown before the On/Off state text. */
  label?: string;
  "aria-label"?: string;
  className?: string;
};

/** A real checkbox with role="switch" and a 44px hit area. It saves at once, so use it for settings, not for form drafts. */
export default function Switch({
  checked,
  onChange,
  disabled,
  problem,
  label,
  className = "",
  "aria-label": ariaLabel,
}: Props) {
  return (
    <label
      className={`wu-switch${problem ? " is-problem" : ""}${className ? ` ${className}` : ""}`}
    >
      <input
        type="checkbox"
        role="switch"
        checked={checked}
        disabled={disabled}
        aria-label={label ? undefined : ariaLabel}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="wu-switch-track" aria-hidden="true" />
      {label && <span className="wu-switch-label">{label}</span>}
      <span className="wu-switch-text">{checked ? "On" : "Off"}</span>
    </label>
  );
}
