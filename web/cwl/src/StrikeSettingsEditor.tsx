import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import ConfirmDialog from "./ConfirmDialog";

import RolePicker, { type RoleChoice } from "./RolePicker";
export type StrikeRole = RoleChoice;
export type StrikeSettings = {
  revision: number;
  strike_limit: number;
  no_attack_opponents?: string[];
  no_attack_names?: Record<string, string>;
  excluded_roles: StrikeRole[];
  roles: StrikeRole[];
  leaves: {
    discord_id: string;
    display_name: string;
    player_tags: string[];
    resume_date: string;
    revision: number;
  }[];
};
export default function StrikeSettingsEditor({
  settings,
  onSaved,
  onDirty,
  onBusy,
}: {
  settings: StrikeSettings;
  onSaved: (settings: StrikeSettings) => void;
  onDirty: (dirty: boolean) => void;
  onBusy: (busy: boolean) => void;
}) {
  const [roles, setRoles] = useState(settings.excluded_roles);
  const [limit, setLimit] = useState(String(settings.strike_limit));
  const [opponents, setOpponents] = useState(
    (settings.no_attack_opponents ?? []).join("\n"),
  );
  const [error, setError] = useState("");
  const [conflict, setConflict] = useState(false);
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(false);
  const [saved, setSaved] = useState(false);
  const active = useRef(true);
  const writing = useRef(false);
  const dirty =
    opponents !== (settings.no_attack_opponents ?? []).join("\n") ||
    limit !== String(settings.strike_limit) ||
    roles
      .map((role) => role.id)
      .sort()
      .join(",") !==
      settings.excluded_roles
        .map((role) => role.id)
        .sort()
        .join(",");
  useEffect(() => {
    active.current = true;
    return () => {
      active.current = false;
    };
  }, []);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);
  async function save() {
    if (
      writing.current ||
      conflict ||
      !dirty ||
      !/^(?:[1-9]|1[0-9]|20)$/.test(limit)
    )
      return;
    writing.current = true;
    setBusy(true);
    onBusy(true);
    setError("");
    setSaved(false);
    try {
      const receipt = await api<{
        revision: number;
        strike_limit: number;
        no_attack_opponents: string[];
        no_attack_names: Record<string, string>;
      }>("/strikes/settings/roles", "PUT", {
        revision: settings.revision,
        role_ids: roles.map((role) => role.id),
        strike_limit: Number(limit),
        no_attack_opponents: opponents.split(/[\s,]+/).filter(Boolean),
      });
      if (!active.current) return;
      // Adopt only this write's receipt, never a fresh read paired with an old draft.
      onSaved({
        ...settings,
        revision: receipt.revision,
        strike_limit: receipt.strike_limit,
        excluded_roles: roles,
        no_attack_opponents: receipt.no_attack_opponents,
        no_attack_names: receipt.no_attack_names,
      });
      setOpponents(receipt.no_attack_opponents.join("\n"));
      setSaved(true);
    } catch (cause) {
      if (!active.current) return;
      setConflict(cause instanceof ApiError && cause.status === 409);
      setError(
        cause instanceof ApiError && cause.status === 409
          ? "Changed by someone else · Reload"
          : cause instanceof Error
            ? cause.message
            : "Could not save settings.",
      );
    } finally {
      writing.current = false;
      if (active.current) {
        setBusy(false);
        onBusy(false);
      }
    }
  }
  async function reloadSettings() {
    setReload(false);
    setBusy(true);
    onBusy(true);
    try {
      const current = await api<StrikeSettings>("/strikes/settings");
      if (!active.current) return;
      setRoles(current.excluded_roles);
      setLimit(String(current.strike_limit));
      setOpponents((current.no_attack_opponents ?? []).join("\n"));
      onSaved(current);
      setConflict(false);
      setError("");
      setSaved(false);
    } catch (cause) {
      if (active.current)
        setError(
          cause instanceof Error ? cause.message : "Could not reload settings.",
        );
    } finally {
      if (active.current) {
        setBusy(false);
        onBusy(false);
      }
    }
  }
  return (
    <section
      className="card strikes-form"
      aria-label="Strike settings"
      aria-busy={busy}
    >
      <h2>Strike settings</h2>
      {error && (
        <div className="notice error" role="alert">
          {error}
          {conflict && (
            <button disabled={busy} onClick={() => setReload(true)}>
              Reload
            </button>
          )}
        </div>
      )}
      {saved && <p role="status">Settings saved.</p>}
      <label>
        Strike limit
        <input
          type="number"
          min={1}
          max={20}
          step={1}
          value={limit}
          disabled={busy}
          onChange={(event) => {
            setLimit(event.target.value);
            setSaved(false);
          }}
        />
      </label>
      <p>Marks accounts at this many active strikes. No automatic action.</p>
      <h3>No-attack opponents</h3>
      <p>Wars against these clans never give strikes.</p>
      {[...new Set(opponents.split(/[\s,]+/).filter(Boolean))].map((value) => (
        <p key={value}>
          {settings.no_attack_names?.[value.toUpperCase()] ||
            (value.toUpperCase() === "#2CYVV92R"
              ? "NO WAR"
              : "Name unavailable")}{" "}
          · {value}
        </p>
      ))}
      <label>
        Opponent clan tags (one per line)
        <textarea
          value={opponents}
          disabled={busy}
          onChange={(event) => {
            setOpponents(event.target.value);
            setSaved(false);
          }}
        />
      </label>
      <h3>Exempt roles</h3>
      <p>Members with these roles do not receive automatic war strikes.</p>
      <div className="strikes-role-list">
        {roles.map((role) => (
          <div key={role.id}>
            <span title={role.id}>
              {/^Role \d+$/.test(role.name) ? "Unavailable role" : role.name}
            </span>
            <button
              disabled={busy}
              aria-label={`Remove ${role.name}`}
              onClick={() => {
                setRoles((current) =>
                  current.filter((item) => item.id !== role.id),
                );
                setSaved(false);
              }}
            >
              Remove
            </button>
          </div>
        ))}
      </div>
      <RolePicker
        roles={settings.roles}
        selected={roles.map((role) => role.id)}
        disabled={busy}
        label="Find exempt role"
        optionsLabel="Available exempt roles"
        onChoose={(role) => {
          setRoles((current) => [...current, role]);
          setSaved(false);
        }}
      />
      <div className="strikes-inline">
        <button
          className="primary"
          disabled={
            busy || conflict || !dirty || !/^(?:[1-9]|1[0-9]|20)$/.test(limit)
          }
          onClick={() => void save()}
        >
          Save settings
        </button>
        {dirty && <span>Unsaved changes</span>}
      </div>
      {reload && (
        <ConfirmDialog
          heading="Reload settings?"
          text="Discard your unsaved role and strike-limit edits and load the latest settings?"
          confirmLabel="Reload"
          cancelLabel="Keep editing"
          onCancel={() => setReload(false)}
          onConfirm={() => void reloadSettings()}
        />
      )}
    </section>
  );
}
