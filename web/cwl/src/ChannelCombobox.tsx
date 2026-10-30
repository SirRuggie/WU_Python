import { useEffect, useId, useState, type KeyboardEvent } from "react";
import type { AnnouncementChannel } from "./announcements";
import { filterChannels } from "./channelSearch";
import "./ChannelCombobox.css";

type Props = {
  label: string;
  channels: AnnouncementChannel[];
  value: string;
  disabled: boolean;
  onChange: (value: string) => void;
  onResolve?: (value: string) => void;
};
const visibleLimit = 30;

export default function ChannelCombobox({
  label,
  channels,
  value,
  disabled,
  onChange,
  onResolve,
}: Props) {
  const id = useId();
  const inputId = `${id}-input`;
  const listId = `${id}-list`;
  const hintId = `${id}-hint`;
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const chosen = channels.find((channel) => channel.id === value);
  const matching = filterChannels(channels, query);
  const lookupId = query.trim();
  const canResolve =
    !!onResolve &&
    /^[0-9]{15,22}$/.test(lookupId) &&
    !channels.some((channel) => channel.id === lookupId);
  const visible = canResolve
    ? [{ id: lookupId, name: "Look up channel or forum post ID", type: -1 }]
    : matching.slice(0, visibleLimit);
  const activeOption =
    open && visible[active] ? `${id}-option-${active}` : undefined;
  useEffect(() => {
    if (!open)
      setQuery(
        value
          ? chosen
            ? `#${chosen.name} · ${chosen.id}`
            : `Channel ${value} (unavailable)`
          : "",
      );
  }, [value, chosen?.name, open]);
  useEffect(() => {
    if (disabled) setOpen(false);
  }, [disabled]);
  useEffect(() => {
    if (activeOption)
      document
        .getElementById(activeOption)
        ?.scrollIntoView({ block: "nearest" });
  }, [activeOption]);
  const choose = (channel: AnnouncementChannel) => {
    if (channel.type === -1) onResolve?.(channel.id);
    else onChange(channel.id);
    setOpen(false);
  };
  const keyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      setOpen(false);
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      if (!open) {
        setQuery("");
        setOpen(true);
        setActive(0);
        return;
      }
      setActive((current) =>
        visible.length
          ? (current + (event.key === "ArrowDown" ? 1 : -1) + visible.length) %
            visible.length
          : 0,
      );
    }
    if (event.key === "Enter" && open) {
      event.preventDefault();
      if (visible[active]) choose(visible[active]);
    }
  };
  return (
    <div className="channel-combobox">
      <label htmlFor={inputId}>{label}</label>
      <div className="channel-combobox-input">
        <input
          id={inputId}
          role="combobox"
          type="text"
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={activeOption}
          aria-describedby={hintId}
          placeholder="Search channels and forum posts"
          value={query}
          disabled={disabled}
          onFocus={() => {
            setQuery("");
            setActive(0);
            setOpen(true);
          }}
          onBlur={() => setOpen(false)}
          onChange={(event) => {
            setQuery(event.target.value);
            setActive(0);
            setOpen(true);
          }}
          onKeyDown={keyDown}
        />
        <button
          type="button"
          aria-label={`Clear ${label.toLowerCase()}`}
          disabled={disabled || !value}
          onClick={() => {
            onChange("");
            setOpen(false);
          }}
        >
          Clear
        </button>
      </div>
      <small id={hintId}>
        {onResolve
          ? "Search active forum posts and channels, or paste a post ID and choose Look up. "
          : "Type part of a channel name or ID. "}
        <span className="channel-keyboard-hint">
          Use arrow keys and Enter to choose; Escape closes results.
        </span>
      </small>
      {open && !disabled && (
        <div
          id={listId}
          role="listbox"
          aria-label={`${label} results`}
          className="channel-results"
        >
          {visible.length ? (
            visible.map((channel, index) => (
              <button
                type="button"
                role="option"
                id={`${id}-option-${index}`}
                aria-selected={channel.id === value}
                className={index === active ? "active" : ""}
                key={channel.id}
                tabIndex={-1}
                onMouseDown={(event) => event.preventDefault()}
                onClick={() => choose(channel)}
              >
                <span>#{channel.name}</span>
                <small>{channel.id}</small>
              </button>
            ))
          ) : (
            <p role="status">No channels match “{query}”.</p>
          )}
          {matching.length > visibleLimit && (
            <small className="channel-more">
              Showing {visibleLimit} of {matching.length} channels. Keep typing
              to narrow results.
            </small>
          )}
        </div>
      )}
    </div>
  );
}
