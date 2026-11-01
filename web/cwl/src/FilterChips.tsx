import "./FilterChips.css";
export default function FilterChips<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled = false,
  className = "",
}: {
  label: string;
  value: T;
  options: { value: T; label: string; count: number }[];
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div className={`filter-chips ${className}`} aria-label={label}>
      {options.map((option) => (
        <button
          type="button"
          key={option.value}
          aria-pressed={value === option.value}
          disabled={disabled}
          onClick={() => onChange(option.value)}
        >
          {option.label} <small>{option.count}</small>
        </button>
      ))}
    </div>
  );
}
