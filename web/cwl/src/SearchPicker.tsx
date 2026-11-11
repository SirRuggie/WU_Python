import {
  useEffect,
  useId,
  useRef,
  useState,
  type FocusEvent,
  type KeyboardEvent,
  type ReactNode,
  type Ref,
} from "react";
import { createPortal } from "react-dom";
import { ChevronDown, Search, X } from "lucide-react";
import "./SearchPicker.css";

export type PickerOption = {
  value: string;
  label: string;
  /** Second line, for example the category or the GMT offset. */
  detail?: string;
  /** Decorative icon or flag. Hidden from screen readers. */
  icon?: ReactNode;
  /** When set, the row shows this note and cannot be selected. */
  disabledNote?: string;
};

type Props = {
  label: string;
  value: string;
  /** All options. Used for the default search and to show the value. */
  options: PickerOption[];
  onChange: (value: string) => void;
  /** Closed field text when nothing is selected. */
  placeholder: string;
  searchPlaceholder: string;
  /** Shown when the search has no result. */
  emptyText: string;
  disabled?: boolean;
  /** Shows a remove button beside a selected value. */
  clearable?: boolean;
  /** Shown when the value is not in options (missing or not loaded yet). */
  fallback?: PickerOption;
  /** Own search, for example ranked or loaded data. */
  search?: (query: string) => PickerOption[];
  /** Runs each time the list opens, for example to load data. */
  onOpen?: () => void;
  /** Extra status in the list, for example a load error. */
  status?: string;
  triggerRef?: Ref<HTMLButtonElement>;
  limit?: number;
};

const PHONE_QUERY = "(max-width: 700px)";
const CLOSE_DELAY_MS = 250;

function usePhone() {
  const [phone, setPhone] = useState(
    () =>
      typeof window !== "undefined" &&
      !!window.matchMedia?.(PHONE_QUERY).matches,
  );
  useEffect(() => {
    const query = window.matchMedia?.(PHONE_QUERY);
    if (!query) return;
    const update = () => setPhone(query.matches);
    update();
    query.addEventListener?.("change", update);
    return () => query.removeEventListener?.("change", update);
  }, []);
  return phone;
}

export function filterOptions(options: PickerOption[], query: string) {
  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  if (!words.length) return options;
  return options.filter((option) => {
    const text = `${option.label} ${option.detail || ""}`.toLowerCase();
    return words.every((word) => text.includes(word));
  });
}

function OptionBody({ option }: { option: PickerOption }) {
  const detail = [option.detail, option.disabledNote]
    .filter(Boolean)
    .join(" · ");
  return (
    <>
      {option.icon && (
        <span className="search-picker-icon" aria-hidden="true">
          {option.icon}
        </span>
      )}
      <span className="search-picker-text">
        <span className="search-picker-name">{option.label}</span>
        {detail && <small>{detail}</small>}
      </span>
    </>
  );
}

/**
 * Field that opens a search list. On a phone the list is a full-screen
 * sheet above the keyboard; on wider screens it opens under the field and
 * moves the content below it down. Selecting a row only calls onChange.
 */
export default function SearchPicker({
  label,
  value,
  options,
  onChange,
  placeholder,
  searchPlaceholder,
  emptyText,
  disabled = false,
  clearable = false,
  fallback,
  search,
  onOpen,
  status,
  triggerRef,
  limit = 50,
}: Props) {
  const id = useId();
  const labelId = `${id}-label`;
  const valueId = `${id}-value`;
  const inputId = `${id}-input`;
  const listId = `${id}-list`;
  const sheetTitleId = `${id}-title`;
  const phone = usePhone();
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const trigger = useRef<HTMLButtonElement | null>(null);
  const input = useRef<HTMLInputElement>(null);
  const sheet = useRef<HTMLDialogElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const closing = useRef(false);
  const closeTimer = useRef(0);

  const selected =
    options.find((option) => option.value === value) ||
    (value && fallback?.value === value ? fallback : undefined);
  const matching = open
    ? search
      ? search(query)
      : filterOptions(options, query)
    : [];
  const visible = matching.slice(0, limit);
  const activeId =
    open && visible[active] ? `${id}-option-${active}` : undefined;

  function setTrigger(node: HTMLButtonElement | null) {
    trigger.current = node;
    if (typeof triggerRef === "function") triggerRef(node);
    else if (triggerRef) triggerRef.current = node;
  }

  function openPicker() {
    if (disabled) return;
    setQuery("");
    setActive(0);
    setOpen(true);
    onOpen?.();
    if (phone) {
      // Open and focus in the same tap so the phone shows its keyboard.
      if (!sheet.current?.open) sheet.current?.showModal?.();
      input.current?.focus();
    }
  }

  function close(returnFocus: boolean) {
    window.clearTimeout(closeTimer.current);
    closing.current = false;
    setOpen(false);
    setQuery("");
    if (sheet.current?.open) sheet.current.close?.();
    if (returnFocus) trigger.current?.focus({ preventScroll: true });
  }

  function choose(option: PickerOption) {
    if (option.disabledNote || closing.current) return;
    // Like a native select: picking the current value changes nothing.
    if (option.value === value) {
      close(true);
      return;
    }
    onChange(option.value);
    if (!phone) {
      close(true);
      return;
    }
    // Phone: keep the sheet up for a moment so a quick second tap lands on
    // the sheet, not on a button behind it (for example "Add clock").
    closing.current = true;
    closeTimer.current = window.setTimeout(() => {
      closing.current = false;
      close(true);
    }, CLOSE_DELAY_MS);
  }

  // Desktop: focus the search after the panel renders.
  useEffect(() => {
    if (open && !phone) input.current?.focus();
  }, [open, phone]);

  useEffect(() => {
    if (disabled && open) close(false);
  }, [disabled]);

  // A rotation across the phone width closes the list instead of leaving it
  // open in a layout that was never shown.
  useEffect(() => {
    if (open) close(false);
  }, [phone]);

  // Phone: fit the sheet to the visible area, which shrinks for the keyboard.
  useEffect(() => {
    if (!phone || !open) return;
    const viewport = window.visualViewport;
    const node = sheet.current;
    if (!viewport || !node) return;
    const fit = () => {
      node.style.setProperty("--search-picker-height", `${viewport.height}px`);
      node.style.setProperty("--search-picker-top", `${viewport.offsetTop}px`);
    };
    fit();
    viewport.addEventListener("resize", fit);
    viewport.addEventListener("scroll", fit);
    return () => {
      viewport.removeEventListener("resize", fit);
      viewport.removeEventListener("scroll", fit);
    };
  }, [phone, open]);

  useEffect(() => {
    if (activeId)
      document.getElementById(activeId)?.scrollIntoView?.({ block: "nearest" });
  }, [activeId]);

  function keyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      close(true);
    } else if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!visible.length) return;
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive(
        (current) => (current + step + visible.length) % visible.length,
      );
    } else if (event.key === "Enter") {
      event.preventDefault();
      if (visible[active]) choose(visible[active]);
    }
  }

  function blur(event: FocusEvent<HTMLDivElement>) {
    if (phone || !open) return;
    if (!box.current?.contains(event.relatedTarget as Node | null))
      close(false);
  }

  const statusText =
    status ||
    (open && !visible.length
      ? emptyText
      : matching.length > visible.length
        ? `Showing ${visible.length} of ${matching.length}. Keep typing to narrow the list.`
        : "");

  const panel = (
    <div
      className="search-picker-panel"
      onMouseDown={(event) => {
        // Keep focus in the search when the panel padding or status is
        // pressed (Safari does not focus buttons, so blur would close it).
        if (event.target !== input.current) event.preventDefault();
      }}
    >
      <div className="search-picker-search">
        <Search aria-hidden="true" size={18} />
        <input
          ref={input}
          id={inputId}
          type="text"
          role="combobox"
          inputMode="search"
          enterKeyHint="search"
          autoComplete="off"
          autoCorrect="off"
          spellCheck={false}
          aria-label={`Search ${label.toLowerCase()}`}
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={activeId}
          placeholder={searchPlaceholder}
          value={query}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
          }}
          onKeyDown={keyDown}
        />
      </div>
      <ul
        id={listId}
        role="listbox"
        aria-label={`${label} results`}
        className="search-picker-list"
      >
        {open &&
          visible.map((option, index) => (
            <li
              key={option.value}
              id={`${id}-option-${index}`}
              role="option"
              aria-selected={option.value === value}
              aria-disabled={option.disabledNote ? true : undefined}
              className={index === active ? "is-active" : undefined}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => choose(option)}
            >
              <OptionBody option={option} />
            </li>
          ))}
      </ul>
      {statusText && (
        <p className="search-picker-status" role="status">
          {statusText}
        </p>
      )}
    </div>
  );

  return (
    <div className="search-picker" ref={box} onBlur={blur}>
      <span className="search-picker-label" id={labelId}>
        {label}
      </span>
      <div className="search-picker-field">
        <button
          ref={setTrigger}
          type="button"
          className="search-picker-trigger"
          aria-haspopup={phone ? "dialog" : "listbox"}
          aria-expanded={open}
          aria-labelledby={`${labelId} ${valueId}`}
          disabled={disabled}
          onMouseDown={(event) => {
            // Safari: keep focus in the open search so this press closes it.
            if (open && !phone) event.preventDefault();
          }}
          onClick={() => (open ? close(true) : openPicker())}
        >
          <span id={valueId} className="search-picker-value">
            {selected ? (
              <OptionBody option={selected} />
            ) : (
              <span className="search-picker-placeholder">{placeholder}</span>
            )}
          </span>
          <ChevronDown
            className="search-picker-chevron"
            aria-hidden="true"
            size={20}
          />
        </button>
        {clearable && value && (
          <button
            type="button"
            className="search-picker-clear"
            aria-label={`Remove ${label.toLowerCase()}`}
            disabled={disabled}
            onClick={() => {
              onChange("");
              close(true);
            }}
          >
            <X aria-hidden="true" size={18} />
          </button>
        )}
      </div>
      {!phone && open && panel}
      {phone &&
        createPortal(
          <dialog
            ref={sheet}
            className="search-picker-sheet"
            aria-labelledby={sheetTitleId}
            onCancel={(event) => {
              // React passes cancel up through the portal. Stop it so a
              // dialog around this field (Add clock) stays open.
              event.preventDefault();
              event.stopPropagation();
              close(true);
            }}
          >
            <header className="search-picker-sheet-head">
              <h2 id={sheetTitleId}>{label}</h2>
              <button
                type="button"
                className="search-picker-close"
                onClick={() => close(true)}
              >
                Close
              </button>
            </header>
            {panel}
          </dialog>,
          document.body,
        )}
    </div>
  );
}
