import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import RoleSelect from "./RoleSelect";
import ConfirmDialog from "./ConfirmDialog";
import type { RoleChoice } from "./CommandExtras";
import { useDashboardPermission } from "./DashboardPermissions";
import { Button } from "./rosterUi/primitives";
import "./CwlPoolRoles.css";

type Pool = "main" | "lazy";
type Setting = {
  pool: Pool;
  role_id: string | null;
  revision: number;
  member_basis: string;
  member_count: number;
  progress: Record<string, number>;
  failure: string | null;
};
type State = { pools: Setting[]; roles?: RoleChoice[] };
const title = (pool: Pool) => (pool === "main" ? "Main" : "Lazy");
const nothing = () => {};

export default function CwlPoolRoles({
  onBusy = nothing,
  onDirty = nothing,
}: {
  onBusy?: (value: boolean) => void;
  onDirty?: (value: boolean) => void;
}) {
  const allowed = useDashboardPermission("cwl_settings");
  const [data, setData] = useState<State>();
  const [drafts, setDrafts] = useState<Partial<Record<Pool, string>>>({});
  const [confirmation, setConfirmation] = useState<{
    row: Setting;
    role: string;
  }>();
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const sequence = useRef(0);
  const pending = useRef(false);
  const mounted = useRef(true);
  const dirty = !!data?.pools.some(
    (row) =>
      drafts[row.pool] !== undefined &&
      drafts[row.pool] !== (row.role_id || ""),
  );
  useEffect(() => {
    onBusy(saving);
    return () => onBusy(false);
  }, [saving, onBusy]);
  useEffect(() => {
    onDirty(dirty);
    return () => onDirty(false);
  }, [dirty, onDirty]);

  function failure(cause: unknown) {
    if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
      setData(undefined);
      setDrafts({});
      setConfirmation(undefined);
    }
    setError(
      cause instanceof Error ? cause.message : "Could not load CWL roles.",
    );
  }
  async function read(status = false) {
    const generation = ++sequence.current;
    const result = await api<State>(
      "/pool-roles" + (status ? "?status=1" : ""),
    );
    if (!mounted.current || generation !== sequence.current) return undefined;
    if (
      !Array.isArray(result.pools) ||
      (!status && !Array.isArray(result.roles))
    )
      throw new Error("Could not load CWL roles.");
    setData((previous) => ({
      ...result,
      roles: result.roles || previous?.roles || [],
    }));
    return result;
  }
  async function refresh() {
    setLoading(true);
    try {
      await read();
      setError("");
    } catch (cause) {
      if (mounted.current) failure(cause);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }
  useEffect(() => {
    mounted.current = true;
    if (allowed) void refresh();
    else {
      setData(undefined);
      setDrafts({});
      setConfirmation(undefined);
    }
    return () => {
      mounted.current = false;
      sequence.current++;
    };
  }, [allowed]);
  const active = data?.pools.some(
    (row) => (row.progress.pending || 0) + (row.progress.leased || 0) > 0,
  );
  useEffect(() => {
    if (!allowed || !active || saving || confirmation) return;
    let stopped = false,
      running = false;
    const timer = window.setInterval(async () => {
      if (
        stopped ||
        running ||
        pending.current ||
        document.visibilityState === "hidden"
      )
        return;
      running = true;
      try {
        await read(true);
      } catch (cause) {
        if (!stopped) failure(cause);
      } finally {
        running = false;
      }
    }, 5000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [allowed, active, saving, confirmation]);

  async function review(pool: Pool) {
    if (pending.current) return;
    pending.current = true;
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const latest = await read();
      const row = latest?.pools.find((item) => item.pool === pool);
      if (row)
        setConfirmation({ row, role: drafts[pool] ?? row.role_id ?? "" });
    } catch (cause) {
      if (mounted.current) failure(cause);
    } finally {
      pending.current = false;
      if (mounted.current) setLoading(false);
    }
  }
  async function save() {
    if (pending.current || !confirmation || !allowed) return;
    pending.current = true;
    setSaving(true);
    setError("");
    const generation = ++sequence.current;
    const choice = confirmation;
    setConfirmation(undefined);
    try {
      const result = await api<State>("/pool-roles", "POST", {
        pool: choice.row.pool,
        role_id: choice.role || null,
        revision: choice.row.revision,
        member_basis: choice.row.member_basis,
      });
      if (!mounted.current || generation !== sequence.current) return;
      setData((previous) => ({
        ...result,
        roles: result.roles || previous?.roles || [],
      }));
      setDrafts((current) => {
        const next = { ...current };
        delete next[choice.row.pool];
        return next;
      });
      setNotice(
        choice.role
          ? "Role saved. Updates are queued."
          : "Role turned off. Existing roles stay.",
      );
    } catch (cause) {
      if (mounted.current) failure(cause);
    } finally {
      pending.current = false;
      if (mounted.current) setSaving(false);
    }
  }
  if (!allowed) return null;
  return (
    <section className="cwl-pool-roles" aria-label="CWL roles">
      <div className="cwl-pool-role-heading">
        <h2>CWL roles</h2>
        <Button disabled={loading || saving} onClick={() => void refresh()}>
          Refresh roles
        </Button>
      </div>
      <p>
        Optional. Blank means off. Roles are removed from everyone on the 16th
        at 00:00 UTC.
      </p>
      {loading && <p role="status">Loading roles…</p>}
      {error && <p role="alert">{error}</p>}
      {notice && <p role="status">{notice}</p>}
      {data?.pools.map((row) => {
        const selected = drafts[row.pool] ?? row.role_id ?? "";
        const progress = row.progress;
        const done = (progress.done || 0) + (progress.failed || 0);
        const total = Object.values(progress).reduce((a, b) => a + b, 0);
        return (
          <fieldset className="cwl-pool-role" key={row.pool}>
            <legend>{title(row.pool)}</legend>
            <RoleSelect
              label={title(row.pool) + " role"}
              roles={data.roles || []}
              value={selected}
              disabled={loading || saving}
              onChange={(value) =>
                setDrafts((old) => ({ ...old, [row.pool]: value }))
              }
            />
            <Button
              disabled={loading || saving || (!selected && !row.role_id)}
              onClick={() => void review(row.pool)}
            >
              Save {title(row.pool)} role
            </Button>
            <p role="status">
              {total
                ? `${done} of ${total} updated${progress.failed ? ` · ${progress.failed} failed` : ""}`
                : row.role_id
                  ? "Role is on."
                  : "Off."}
              {row.failure && ` · ${row.failure}`}
            </p>
          </fieldset>
        );
      })}
      {confirmation && (
        <ConfirmDialog
          heading={title(confirmation.row.pool) + " CWL role"}
          text={
            confirmation.role
              ? `Adds role to ${confirmation.row.member_count} members`
              : "Turn off this role? Existing roles stay."
          }
          confirmLabel={confirmation.role ? "Save role" : "Turn off role"}
          cancelLabel="Keep current setting"
          disabled={saving}
          onCancel={() => setConfirmation(undefined)}
          onConfirm={() => void save()}
        />
      )}
    </section>
  );
}
