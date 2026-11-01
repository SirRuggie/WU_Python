import FilterChips from "../FilterChips";
import RoleSelect from "../RoleSelect";
import type { RoleChoice } from "../CommandExtras";
import { membersText as t } from "./strings";
import type { MemberFilters as Filters, MemberStatus } from "./model";
import "./Members.css";
export default function MemberFilters({
  value,
  counts,
  roles,
  onChange,
}: {
  value: Filters;
  counts: Record<MemberStatus, number>;
  roles: RoleChoice[];
  onChange: (next: Filters) => void;
}) {
  const update = (patch: Partial<Filters>) => onChange({ ...value, ...patch });
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
      <label>
        {t.search}
        <input
          type="search"
          value={value.query}
          placeholder={t.searchHint}
          onChange={(e) => update({ query: e.target.value })}
        />
      </label>
      <FilterChips
        label={t.statusLabel}
        value={value.status}
        options={(Object.keys(labels) as MemberStatus[]).map((status) => ({
          value: status,
          label: labels[status],
          count: counts[status],
        }))}
        onChange={(status) => update({ status })}
      />
      <div className="members-filter-tools">
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
      </div>
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
