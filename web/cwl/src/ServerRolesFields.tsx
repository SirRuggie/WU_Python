import { useRef } from "react";
import { ArrowDown, ArrowUp, X } from "lucide-react";
import RolePicker, { roleOption } from "./RolePicker";
import type { ManagementField } from "./serverManagement";
import "./ServerRolesFields.css";

type Entry = {
  role_id: string;
  label: string;
  short_line: string;
  order: number;
};

export default function ServerRolesFields({
  field,
  value,
  onChange,
  disabled,
}: {
  field: ManagementField;
  value: string;
  onChange: (value: string) => void;
  disabled: boolean;
}) {
  const container = useRef<HTMLDivElement>(null);
  let rows: Entry[] = [];
  try {
    rows = JSON.parse(value);
  } catch {
    /* Server validation retains the draft. */
  }
  const roles = (field.options || []).map((option) => ({
    id: option.value,
    name: option.label,
    color: option.color,
  }));
  const update = (next: Entry[]) =>
    onChange(JSON.stringify(next.map((row, order) => ({ ...row, order }))));
  const edit = (index: number, key: "label" | "short_line", next: string) =>
    update(rows.map((row, i) => (i === index ? { ...row, [key]: next } : row)));
  const move = (index: number, offset: number) => {
    const next = [...rows];
    [next[index], next[index + offset]] = [next[index + offset], next[index]];
    update(next);
  };
  const remove = (index: number) => {
    const next = rows[index + 1] || rows[index - 1];
    update(rows.filter((_, i) => i !== index));
    window.requestAnimationFrame(() => {
      const target = next
        ? container.current?.querySelector<HTMLInputElement>(
            `#server-role-label-${next.role_id}`,
          )
        : container.current?.querySelector<HTMLButtonElement>(
            ".search-picker-trigger",
          );
      target?.focus();
    });
  };
  return (
    <div className="server-role-fields" ref={container}>
      {field.error && <p role="alert">{field.error}</p>}
      <p className="muted" aria-live="polite">
        {rows.length} of 25 roles
      </p>
      {!rows.length && (
        <p>
          No server roles yet. Add a role to show it in Roles and clan links.
        </p>
      )}
      {rows.map((row, index) => {
        const role = roles.find((role) => role.id === row.role_id) || {
          id: row.role_id,
          name: "Unavailable role",
        };
        return (
          <section
            className="server-role-entry"
            key={row.role_id}
            aria-label={role.name}
          >
            <div className="server-role-entry-heading">
              <strong>
                {roleOption(role).icon}
                {role.name}
              </strong>
              <div className="server-role-entry-actions">
                <button
                  type="button"
                  aria-label={`Move ${row.label} up`}
                  disabled={disabled || index === 0}
                  onClick={() => move(index, -1)}
                >
                  <ArrowUp size={18} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label={`Move ${row.label} down`}
                  disabled={disabled || index === rows.length - 1}
                  onClick={() => move(index, 1)}
                >
                  <ArrowDown size={18} aria-hidden="true" />
                </button>
                <button
                  type="button"
                  aria-label={`Remove ${role.name}`}
                  disabled={disabled}
                  onClick={() => remove(index)}
                >
                  <X size={18} aria-hidden="true" />
                </button>
              </div>
            </div>
            {field.role_conflicts?.includes(row.role_id) && (
              <p role="status">
                Also used for a Town Hall. Remove it from one list.
              </p>
            )}
            <label htmlFor={`server-role-label-${row.role_id}`}>
              Label <span className="muted">{row.label.length}/40</span>
            </label>
            <input
              id={`server-role-label-${row.role_id}`}
              name={`server-role-label-${row.role_id}`}
              autoComplete="off"
              value={row.label}
              maxLength={40}
              required
              disabled={disabled}
              onChange={(event) => edit(index, "label", event.target.value)}
            />
            <label htmlFor={`server-role-line-${row.role_id}`}>
              Short line{" "}
              <span className="muted">{row.short_line.length}/100</span>
            </label>
            <input
              id={`server-role-line-${row.role_id}`}
              name={`server-role-line-${row.role_id}`}
              autoComplete="off"
              value={row.short_line}
              maxLength={100}
              disabled={disabled}
              onChange={(event) =>
                edit(index, "short_line", event.target.value)
              }
            />
          </section>
        );
      })}
      <RolePicker
        label="Add role"
        roles={roles}
        selected={rows.map((row) => row.role_id)}
        disabled={disabled || rows.length >= 25}
        onChoose={(role) =>
          update([
            ...rows,
            {
              role_id: role.id,
              label: role.name.slice(0, 40),
              short_line: "",
              order: rows.length,
            },
          ])
        }
      />
    </div>
  );
}
