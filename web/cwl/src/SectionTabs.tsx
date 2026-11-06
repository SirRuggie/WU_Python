import "./SectionTabs.css";

export default function SectionTabs<T extends string>({
  label,
  items,
  value,
  onChange,
  disabled = false,
  className = "",
}: {
  label: string;
  items: { id: T; label: string }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
}) {
  return (
    <div
      className={`section-tabs ${className}`}
      role="group"
      aria-label={label}
    >
      {items.map((item) => (
        <button
          type="button"
          key={item.id}
          aria-pressed={value === item.id}
          disabled={disabled}
          onClick={() => onChange(item.id)}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
