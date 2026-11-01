import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Change, Run } from "../memberTimezones/types";
import { membersText as t } from "./strings";
export type RoleReview = {
  token: string;
  selected: string[];
  count: number;
  role: { id: string; name: string; protected: boolean };
  operation: "add" | "remove";
};
type RoleFields = {
  role_id?: string;
  operation?: "add" | "remove";
  expected_role_ids?: string[];
  changed?: boolean;
};
type RoleRun = Omit<Run, "rows"> & { rows: (Change & RoleFields)[] };
type RoleStatus = {
  run_id: string;
  state: string;
  started_by?: string;
  stopped_by?: string;
  rows: {
    discord_id: string;
    status: string;
    message: string;
    changed?: boolean;
    role_id?: string;
    operation?: "add" | "remove";
    expected_role_ids?: string[];
  }[];
};
function asRun(value: RoleStatus): RoleRun {
  if (
    !value ||
    typeof value.run_id !== "string" ||
    !["queued", "stopping", "done", "stopped"].includes(value.state) ||
    !Array.isArray(value.rows) ||
    value.rows.length > 10000 ||
    new Set(value.rows.map((row) => row.discord_id)).size !==
      value.rows.length ||
    value.rows.some(
      (row) =>
        !/^\d{15,22}$/.test(row.discord_id) || typeof row.message !== "string",
    )
  )
    throw new Error(t.roleUnavailable);
  return {
    ...value,
    rows: value.rows.map((row) => ({
      ...row,
      revision: 0,
      old_nickname: null,
      new_nickname: null,
      status:
        row.status === "done" && row.changed === false ? "skipped" : row.status,
    })),
  };
}
export default function useRoleRun(
  onDenied: () => void,
  onChanged: () => void,
  enabled = true,
) {
  const [run, setRun] = useState<RoleRun | null>(null),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [uncertain, setUncertainState] = useState(false);
  const version = useRef(0),
    pending = useRef(false),
    alive = useRef(true),
    callbacks = useRef({ onDenied, onChanged });
  callbacks.current = { onDenied, onChanged };
  const uncertainRef = useRef(false);
  function setUncertain(value: boolean) {
    uncertainRef.current = value;
    setUncertainState(value);
  }
  const controllers = useRef(new Set<AbortController>());
  async function request<T>(
    path: string,
    method = "GET",
    body?: unknown,
  ): Promise<T> {
    const controller = new AbortController();
    controllers.current.add(controller);
    const timer = window.setTimeout(() => controller.abort(), 45000);
    try {
      return await api<T>(path, method, body, { signal: controller.signal });
    } finally {
      window.clearTimeout(timer);
      controllers.current.delete(controller);
    }
  }
  function fail(cause: unknown) {
    if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
      setRun(null);
      callbacks.current.onDenied();
    }
    setError(cause instanceof Error ? cause.message : t.roleUnavailable);
  }
  async function read(id: string) {
    const next = asRun(
      await request<RoleStatus>(
        `/manage/members/role-runs/${encodeURIComponent(id)}`,
      ),
    );
    return next;
  }
  async function refresh() {
    if (!enabled) return;
    const generation = ++version.current;
    try {
      const active = await request<{ runs: { run_id: string }[] }>(
        "/manage/members/role-runs?active=1",
      );
      if (!alive.current || generation !== version.current) return;
      if (
        !active ||
        !Array.isArray(active.runs) ||
        active.runs.length > 100 ||
        active.runs.some(
          (row) => typeof row.run_id !== "string" || row.run_id.length > 200,
        )
      )
        throw new Error(t.roleUnavailable);
      const id = active.runs[0]?.run_id || run?.run_id;
      if (id) {
        const next = await read(id);
        if (alive.current && generation === version.current) {
          setRun(next);
          setError("");
          setUncertain(false);
          if (uncertain) callbacks.current.onChanged();
        }
      } else {
        setError("");
        setUncertain(false);
        if (uncertain) callbacks.current.onChanged();
      }
    } catch (cause) {
      if (alive.current && generation === version.current) fail(cause);
    }
  }
  useEffect(() => {
    alive.current = true;
    if (enabled) void refresh();
    else {
      setRun(null);
      setError("");
      setUncertain(false);
    }
    return () => {
      alive.current = false;
      version.current++;
      for (const controller of controllers.current) controller.abort();
      controllers.current.clear();
    };
  }, [enabled]);
  useEffect(() => {
    if (!enabled || !run || !["queued", "stopping"].includes(run.state)) return;
    let stopped = false,
      inflight = false;
    const check = async () => {
      const generation = version.current;
      if (
        stopped ||
        inflight ||
        pending.current ||
        document.visibilityState === "hidden"
      )
        return;
      inflight = true;
      try {
        const next = await read(run.run_id);
        if (!stopped && alive.current && generation === version.current) {
          setRun(next);
          setError("");
          if (["done", "stopped"].includes(next.state))
            callbacks.current.onChanged();
        }
      } catch (cause) {
        if (!stopped && generation === version.current) fail(cause);
      } finally {
        inflight = false;
      }
    };
    const timer = window.setInterval(() => void check(), 2000);
    void check();
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [enabled, run?.run_id, run?.state]);
  async function confirm(review: RoleReview) {
    if (!enabled || pending.current || uncertainRef.current) return false;
    pending.current = true;
    setBusy(true);
    setError("");
    const generation = ++version.current;
    try {
      const result = await request<{ run_id: string; state: string }>(
        "/manage/members/role-confirm",
        "POST",
        {
          token: review.token,
          selected: review.selected,
          protected_confirmed: review.role.protected,
        },
      );
      if (!result || typeof result.run_id !== "string")
        throw new Error(t.roleUncertain);
      const next = await read(result.run_id);
      if (alive.current && generation === version.current) {
        setRun(next);
        setUncertain(false);
      }
      return alive.current && generation === version.current;
    } catch (cause) {
      if (alive.current && generation === version.current) {
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          fail(cause);
        else if (
          cause instanceof ApiError &&
          [400, 404, 409, 422].includes(cause.status)
        )
          fail(cause);
        else {
          setRun(null);
          setError(t.roleUncertain);
          setUncertain(true);
        }
      }
      return false;
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  async function stop() {
    if (!enabled || !run || pending.current) return;
    pending.current = true;
    setBusy(true);
    const generation = ++version.current;
    try {
      await request(
        `/manage/members/role-runs/${encodeURIComponent(run.run_id)}/stop`,
        "POST",
        {},
      );
      const next = await read(run.run_id);
      if (alive.current && generation === version.current) setRun(next);
    } catch (cause) {
      if (alive.current && generation === version.current) fail(cause);
    } finally {
      pending.current = false;
      if (alive.current) setBusy(false);
    }
  }
  return {
    run,
    error,
    busy,
    active: uncertain || (!!run && ["queued", "stopping"].includes(run.state)),
    uncertain,
    confirm,
    stop,
    refresh,
  };
}
