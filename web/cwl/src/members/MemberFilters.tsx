import { searchInputProps } from "../inputProps";
import { useState, type ReactNode } from "react";
import FilterChips from "../FilterChips";
import RoleSelect from "../RoleSelect";
import type { RoleChoice } from "../CommandExtras";
import { membersText as t } from "./strings";
import type { MemberFilters as Filters, MemberStatus } from "./model";
import ActionPanel from "../ActionPanel";
import ListToolbar from "../rosterUi/ListToolbar";
import FiltersTrigger from "../rosterUi/FiltersTrigger";
import SortTrigger from "../rosterUi/SortTrigger";
import { Button } from "../rosterUi/primitives";
import "./Members.css";
export default function MemberFilters({
  value,
  counts,
  roles,
  sort,
  onSort,
  onChange,
  actions,
}: {
  actions?: ReactNode;
  value: Filters;
  counts: Record<MemberStatus, number>;
  roles: RoleChoice[];
  sort: "name" | "time_zone";
  onSort: (value: "name" | "time_zone") => void;
  onChange: (next: Filters) => void;
}) {
  const [panel, setPanel] = useState<"filters" | "sort" | null>(null);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const update = (patch: Partial<Filters>) => onChange({ ...value, ...patch });
  const filterCount =
    value.roles.length + Number(value.bots) + Number(value.selectedOnly);
  const labels: Record<MemberStatus, string> = {
    all: t.all,
    needs_flag: t.needsFlag,
    no_time_zone: t.noTimeZone,
    check_name: t.checkName,
  };
  const active =
    !!value.query ||
    value.status !== "all" ||
    !!value.roles.length ||
    value.bots ||
    value.selectedOnly;
  return (
    <section className="members-filters" aria-label={t.search}>
      <div className="members-search-line">
        <label>
          <span className="members-search-label">{t.search}</span>
          <input
            {...searchInputProps}
            type="search"
            value={value.query}
            placeholder={t.searchHint}
            onChange={(e) => update({ query: e.target.value })}
          />
        </label>
      </div>
      <ListToolbar
        className="members-filter-tools"
        filters={
          <FiltersTrigger
            count={filterCount}
            open={panel === "filters"}
            onClick={(event) => {
              setTrigger(event.currentTarget);
              setPanel("filters");
            }}
          />
        }
        sort={
          <SortTrigger
            label={sort === "name" ? "Name" : "Time zone"}
            aria-expanded={panel === "sort"}
            onClick={(event) => {
              setTrigger(event.currentTarget);
              setPanel("sort");
            }}
          />
        }
        actions={actions}
      />
      {panel === "filters" && (
        <ActionPanel
          title="Filter members"
          trigger={trigger}
          onClose={() => setPanel(null)}
        >
          <div className="members-filter-panel">
            <RoleSelect
              label={t.roleFilter}
              roles={[{ id: "none", name: t.noRole }, ...roles]}
              value=""
              onChange={(role) => {
                if (role && !value.roles.includes(role))
                  update({ roles: [...value.roles, role] });
              }}
            />
            <label className="members-checkbox">
              <input
                type="checkbox"
                checked={value.bots}
                onChange={(e) => update({ bots: e.target.checked })}
              />
              {t.bots}
            </label>
            <label className="members-checkbox">
              <input
                type="checkbox"
                checked={value.selectedOnly}
                onChange={(event) =>
                  update({ selectedOnly: event.target.checked })
                }
              />
              {t.selectedOnly}
            </label>
          </div>
        </ActionPanel>
      )}
      {panel === "sort" && (
        <ActionPanel
          title="Sort members"
          trigger={trigger}
          onClose={() => setPanel(null)}
        >
          <div className="members-sort-options">
            {(
              [
                ["name", "Name"],
                ["time_zone", "Time zone"],
              ] as const
            ).map(([value, label]) => (
              <Button
                key={value}
                aria-pressed={sort === value}
                onClick={() => {
                  onSort(value);
                  setPanel(null);
                }}
              >
                {label}
              </Button>
            ))}
          </div>
        </ActionPanel>
      )}
      <FilterChips
        variant="pill"
        label={t.statusLabel}
        value={value.status}
        options={(Object.keys(labels) as MemberStatus[]).map((status) => ({
          value: status,
          label: labels[status],
          count: counts[status],
        }))}
        onChange={(status) => update({ status })}
      />
      {active && (
        <div className="members-active-filters" aria-label={t.clearAll}>
          {value.query && (
            <button onClick={() => update({ query: "" })}>
              {value.query} ×
            </button>
          )}
          {value.status !== "all" && (
            <button onClick={() => update({ status: "all" })}>
              {labels[value.status]} ×
            </button>
          )}
          {value.roles.map((id) => (
            <button
              key={id}
              onClick={() =>
                update({ roles: value.roles.filter((role) => role !== id) })
              }
            >
              {id === "none"
                ? t.noRole
                : roles.find((role) => role.id === id)?.name || t.roles}{" "}
              ×
            </button>
          ))}
          {value.bots && (
            <button onClick={() => update({ bots: false })}>{t.bots} ×</button>
          )}
          {value.selectedOnly && (
            <button onClick={() => update({ selectedOnly: false })}>
              {t.selectedOnly} ×
            </button>
          )}
          <button
            onClick={() =>
              onChange({
                query: "",
                status: "all",
                roles: [],
                bots: false,
                selectedOnly: false,
              })
            }
          >
            {t.clearAll}
          </button>
        </div>
      )}
    </section>
  );
}
