import { useRef } from "react";

type Props<T extends string> = {
  sections: readonly T[];
  value: T;
  disabled: boolean;
  onChange: (value: T) => void;
};

export default function ClanSettingsNavigation<T extends string>({
  sections,
  value,
  disabled,
  onChange,
}: Props<T>) {
  const buttons = useRef<(HTMLButtonElement | null)[]>([]);
  return (
    <div className="clan-tabs" role="tablist" aria-label="Clan settings">
      {sections.map((section, index) => (
        <button
          key={section}
          ref={(element) => {
            buttons.current[index] = element;
          }}
          id={`clan-section-${index}`}
          role="tab"
          aria-selected={value === section}
          aria-controls="clan-settings-panel"
          tabIndex={value === section ? 0 : -1}
          disabled={disabled}
          onClick={() => onChange(section)}
          onKeyDown={(event) => {
            let target: number;
            if (event.key === "ArrowRight")
              target = (index + 1) % sections.length;
            else if (event.key === "ArrowLeft")
              target = (index - 1 + sections.length) % sections.length;
            else if (event.key === "Home") target = 0;
            else if (event.key === "End") target = sections.length - 1;
            else return;
            event.preventDefault();
            buttons.current[target]?.focus();
          }}
        >
          {section}
        </button>
      ))}
    </div>
  );
}
