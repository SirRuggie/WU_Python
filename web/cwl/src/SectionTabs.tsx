import {
  useEffect,
  useId,
  useRef,
  useState,
  type HTMLAttributes,
  type ReactNode,
} from "react";
import useChoiceRail from "./useChoiceRail";
import "./SectionTabs.css";
import "./ChoiceGroupLayout.css";

export const sectionTabId = (base: string, value: string) =>
  `${base}-tab-${value}`;
export const sectionPanelId = (base: string, value: string) =>
  `${base}-panel-${value}`;

export function SectionTabPanel({
  id,
  value,
  children,
  ...props
}: { id: string; value: string; children: ReactNode } & Omit<
  HTMLAttributes<HTMLDivElement>,
  "id"
>) {
  return (
    <div
      {...props}
      role="tabpanel"
      id={sectionPanelId(id, value)}
      aria-labelledby={sectionTabId(id, value)}
      tabIndex={0}
    >
      {children}
    </div>
  );
}

export default function SectionTabs<T extends string>({
  label,
  items,
  value,
  onChange,
  disabled = false,
  className = "",
  revealSelection = false,
  rootRef,
  mode = "tabs",
  id,
  ...groupProps
}: {
  label: string;
  items: {
    id: T;
    label: ReactNode;
    disabled?: boolean;
    tabId?: string;
    panelId?: string;
  }[];
  value: T;
  onChange: (value: T) => void;
  disabled?: boolean;
  className?: string;
  revealSelection?: boolean;
  rootRef?: (node: HTMLDivElement | null) => void;
  /** A list filter is a segmented control, not a set of content panels. */
  mode?: "tabs" | "segmented";
} & Omit<HTMLAttributes<HTMLDivElement>, "children" | "onChange">) {
  const generatedId = useId();
  const base = id || `section-tabs-${generatedId}`;
  const buttons = useRef(new Map<T, HTMLButtonElement>());
  const [focused, setFocused] = useState(value);
  useEffect(() => setFocused(value), [value]);
  const enabled = disabled
    ? []
    : items.filter((item) => !item.disabled).map((item) => item.id);
  const focusValue = enabled.includes(focused)
    ? focused
    : enabled.includes(value)
      ? value
      : enabled[0];
  const { ref, fadeProps } = useChoiceRail<HTMLDivElement>(
    `${value}\0${items.map((item) => item.id).join("\0")}`,
    revealSelection,
    rootRef,
  );
  return (
    <div
      {...groupProps}
      {...fadeProps}
      id={base}
      ref={ref}
      className={`section-tabs has-horizontal-fades ${className}`}
      role={mode === "tabs" ? "tablist" : "group"}
      aria-label={label}
    >
      {items.map((item) => (
        <button
          type="button"
          key={item.id}
          ref={(node) => {
            if (node) buttons.current.set(item.id, node);
            else buttons.current.delete(item.id);
          }}
          id={
            mode === "tabs"
              ? item.tabId || sectionTabId(base, item.id)
              : undefined
          }
          role={mode === "tabs" ? "tab" : undefined}
          aria-selected={mode === "tabs" ? value === item.id : undefined}
          aria-controls={
            mode === "tabs"
              ? item.panelId || sectionPanelId(base, item.id)
              : undefined
          }
          aria-pressed={mode === "segmented" ? value === item.id : undefined}
          tabIndex={
            mode === "tabs" ? (focusValue === item.id ? 0 : -1) : undefined
          }
          disabled={disabled || item.disabled}
          onFocus={() => {
            if (mode === "tabs") setFocused(item.id);
          }}
          onClick={() => onChange(item.id)}
          onKeyDown={(event) => {
            if (mode !== "tabs" || !enabled.length) return;
            let target: T;
            const index = enabled.indexOf(item.id);
            if (event.key === "ArrowRight")
              target = enabled[(index + 1) % enabled.length];
            else if (event.key === "ArrowLeft")
              target = enabled[(index - 1 + enabled.length) % enabled.length];
            else if (event.key === "Home") target = enabled[0];
            else if (event.key === "End") target = enabled[enabled.length - 1];
            else return;
            event.preventDefault();
            setFocused(target);
            buttons.current.get(target)?.focus();
          }}
        >
          {item.label}
        </button>
      ))}
    </div>
  );
}
