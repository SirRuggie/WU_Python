import { useState } from "react";
import DiscordIdentity from "../DiscordIdentity";
import FilterChips from "../FilterChips";
import type { Change, Member, ReviewCategory } from "./types";
const labels: Record<ReviewCategory, string> = {
  will_change: "Will change",
  needs_flag: "Needs flag",
  no_time_zone: "No time zone",
  already_done: "Already done",
  cant_rename: "Can't rename",
  check_name: "Check name",
};
export function MemberPages({
  page,
  total,
  onChange,
}: {
  page: number;
  total: number;
  onChange: (page: number) => void;
}) {
  const last = Math.max(0, Math.ceil(total / 25) - 1);
  return (
    <nav className="mt-pagination" aria-label="Review pages">
      <button
        aria-label="Previous review members"
        disabled={!page}
        onClick={() => onChange(page - 1)}
      >
        ←
      </button>
      <span aria-label={`Page ${page + 1} of ${last + 1}`}>
        {page + 1}/{last + 1}
      </span>
      <button
        aria-label="Next review members"
        disabled={page >= last}
        onClick={() => onChange(page + 1)}
      >
        →
      </button>
    </nav>
  );
}
export default function NicknameReview({
  rows,
  members,
  selected,
  onSelect,
  onConfirm,
  disabled,
}: {
  rows: Change[];
  members: Member[];
  selected: Set<string>;
  onSelect: (ids: Set<string>) => void;
  onConfirm: () => void;
  disabled: boolean;
}) {
  const [filter, setFilter] = useState<ReviewCategory | "selected">(
      "will_change",
    ),
    [query, setQuery] = useState(""),
    [page, setPage] = useState(0);
  const visible = rows.filter(
    (r) =>
      (filter === "selected"
        ? selected.has(r.discord_id)
        : r.category === filter) &&
      `${r.name || ""} ${r.old_nickname || ""} ${r.new_nickname || ""}`
        .normalize("NFKC")
        .toLocaleLowerCase()
        .includes(query.normalize("NFKC").toLocaleLowerCase()),
  );
  const hidden = rows.filter(
    (r) => selected.has(r.discord_id) && !visible.includes(r),
  ).length;
  const current = Math.min(
    page,
    Math.max(0, Math.ceil(visible.length / 25) - 1),
  );
  return (
    <section aria-label="Nickname review">
      <h2>Review nicknames</h2>
      <FilterChips
        label="Nickname filters"
        value={filter}
        disabled={disabled}
        options={(Object.keys(labels) as ReviewCategory[])
          .filter(
            (k) => k !== "check_name" || rows.some((r) => r.category === k),
          )
          .map((k) => ({
            value: k,
            label: labels[k],
            count: rows.filter((r) => r.category === k).length,
          }))}
        onChange={(f) => {
          setFilter(f);
          setPage(0);
        }}
      />
      <label>
        Search nicknames
        <input
          type="search"
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setPage(0);
          }}
          placeholder="Name or nickname"
        />
      </label>
      <div className="mt-standardize-actions">
        <strong>{selected.size} selected</strong>
        {hidden > 0 && (
          <button
            disabled={disabled}
            onClick={() => {
              setFilter("selected");
              setQuery("");
              setPage(0);
            }}
          >
            {hidden} hidden
          </button>
        )}
        <button disabled={disabled || !selected.size} onClick={onConfirm}>
          Rename {selected.size}
        </button>
        <button
          disabled={disabled || !selected.size}
          onClick={() => onSelect(new Set())}
        >
          Clear
        </button>
      </div>
      <MemberPages page={current} total={visible.length} onChange={setPage} />
      {!visible.length && <p>No members match these filters.</p>}
      <ul className="mt-list">
        {visible.slice(current * 25, (current + 1) * 25).map((r) => (
          <li key={r.discord_id}>
            <label className="mt-check">
              <input
                type="checkbox"
                checked={selected.has(r.discord_id)}
                disabled={!!r.skip_reason || disabled}
                onChange={(e) => {
                  const next = new Set(selected);
                  if (e.target.checked) next.add(r.discord_id);
                  else next.delete(r.discord_id);
                  onSelect(next);
                }}
              />
              <DiscordIdentity
                userId={r.discord_id}
                displayName={r.name}
                resolvedMember={
                  members.find((m) => m.discord_id === r.discord_id)
                    ?.discord_profile || null
                }
                variant="compact"
                contact={false}
              />
            </label>
            <p>
              {r.old_nickname || r.name || "No nickname"}
              {r.new_nickname && r.new_nickname !== r.old_nickname
                ? ` → ${r.new_nickname}`
                : ""}
            </p>
            {r.skip_reason && r.category !== "already_done" && (
              <small>{r.skip_reason}</small>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
