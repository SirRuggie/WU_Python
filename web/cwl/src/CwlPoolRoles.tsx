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
  scanning?: boolean;
};
type State = {
  pools: Setting[];
  roles?: RoleChoice[];
  saved_roles?: Partial<Record<Pool, { name: string; allowed: boolean }>>;
  roles_error?: string;
  worker_warning?: string;
};
function validState(value: State) {
  return (
    !!value &&
    Array.isArray(value.pools) &&
    value.pools.length === 2 &&
    new Set(value.pools.map((row) => row?.pool)).size === 2 &&
    value.pools.every(
      (row) =>
        row &&
        ["main", "lazy"].includes(row.pool) &&
        (row.role_id === null || typeof row.role_id === "string") &&
        Number.isSafeInteger(row.revision) &&
        row.revision >= 0 &&
        Number.isSafeInteger(row.member_count) &&
        row.member_count >= 0 &&
        typeof row.member_basis === "string" &&
        !!row.progress &&
        typeof row.progress === "object" &&
        Object.values(row.progress).every(
          (count) => Number.isSafeInteger(count) && count >= 0,
        ) &&
        (row.failure === null || typeof row.failure === "string"),
    ) &&
    (value.roles === undefined ||
      (Array.isArray(value.roles) &&
        value.roles.every(
          (role) =>
            typeof role.id === "string" && typeof role.name === "string",
        ))) &&
    (value.saved_roles === undefined ||
      (!!value.saved_roles &&
        typeof value.saved_roles === "object" &&
        Object.values(value.saved_roles).every(
          (role) =>
            !!role &&
            typeof role.name === "string" &&
            typeof role.allowed === "boolean",
        ))) &&
    (value.roles_error === undefined ||
      typeof value.roles_error === "string") &&
    (value.worker_warning === undefined ||
      typeof value.worker_warning === "string")
  );
}
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
  const choosing = useRef(false);
  const choicesRequested = useRef(false);
  const [choicesLoaded, setChoicesLoaded] = useState(false);
  const [choicesLoading, setChoicesLoading] = useState(false);
  const opener = useRef<HTMLElement | null>(null);
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
      setChoicesLoaded(false);
      choicesRequested.current = false;
    }
    setError(
      cause instanceof Error ? cause.message : "Could not load CWL roles.",
    );
  }
  async function read(status = false, choices = false) {
    const generation = ++sequence.current;
    const result = await api<State>(
      "/pool-roles" + (choices ? "?choices=1" : status ? "?status=1" : ""),
    );
    if (!mounted.current || generation !== sequence.current) return undefined;
    if (!validState(result) || (choices && !Array.isArray(result.roles)))
      throw new Error("Could not load CWL roles.");
    setData((previous) => ({
      ...result,
      roles: result.roles || previous?.roles || [],
      saved_roles: result.saved_roles || previous?.saved_roles,
      roles_error:
        result.roles === undefined ? previous?.roles_error : result.roles_error,
    }));
    return result;
  }
  async function openChoices() {
    if (choosing.current || choicesLoaded || !allowed) return;
    choicesRequested.current = true;
    choosing.current = true;
    setChoicesLoading(true);
    try {
      const result = await read(false, true);
      if (result && !result.roles_error) setChoicesLoaded(true);
    } catch (cause) {
      if (mounted.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          failure(cause);
        else
          setError(
            "Role choices unavailable. Refresh or turn off a saved role.",
          );
      }
    } finally {
      choosing.current = false;
      if (mounted.current) setChoicesLoading(false);
    }
  }
  async function refresh() {
    setLoading(true);
    try {
      await read(false, choicesRequested.current);
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
      setChoicesLoaded(false);
      choicesRequested.current = false;
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
    (row) =>
      row.scanning ||
      (row.progress.pending || 0) + (row.progress.leased || 0) > 0,
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
        choosing.current ||
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

  async function review(pool: Pool, trigger: HTMLElement) {
    opener.current = trigger;
    if (pending.current) return;
    pending.current = true;
    setLoading(true);
    setError("");
    setNotice("");
    try {
      const clearing =
        (drafts[pool] ??
          data?.pools.find((row) => row.pool === pool)?.role_id ??
          "") === "";
      const latest = await read(clearing);
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
      if (!validState(result))
        throw new Error(
          "Save could not be confirmed. Refresh roles before trying again.",
        );
      setData((previous) => ({
        ...result,
        roles: result.roles || previous?.roles || [],
        saved_roles: result.saved_roles || previous?.saved_roles,
        roles_error:
          result.roles === undefined
            ? previous?.roles_error
            : result.roles_error,
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
        at midnight UTC.
      </p>
      {loading && <p role="status">Loading roles…</p>}
      {error && <p role="alert">{error}</p>}
      {data?.worker_warning && <p role="status">{data.worker_warning}</p>}
      {data?.roles_error && <p role="status">{data.roles_error}</p>}
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
              unavailableLabel={
                data.saved_roles?.[row.pool]?.name || "Saved role"
              }
              value={selected}
              disabled={loading || saving}
              onOpen={() => void openChoices()}
              onChange={(value) =>
                setDrafts((old) => ({ ...old, [row.pool]: value }))
              }
            />
            {row.role_id && data.saved_roles?.[row.pool]?.allowed === false && (
              <p role="status">
                Saved role is no longer eligible. Choose another role or turn it
                off.
              </p>
            )}
            <Button
              disabled={
                loading ||
                saving ||
                choicesLoading ||
                selected === (row.role_id || "")
              }
              onClick={(event) => void review(row.pool, event.currentTarget)}
            >
              Save {title(row.pool)} role
            </Button>
            <p role="status">
              {row.scanning
                ? "Checking role holders…"
                : total
                  ? `${done} of ${total} done${progress.failed ? ` · ${progress.failed} failed` : ""}`
                  : row.failure
                    ? "Needs attention."
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
          returnFocus={() => opener.current}
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
