import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Pool } from "./api";
import type { RosterSnapshot } from "./roster";
import RosterUndoToast from "./RosterUndoToast";
import type { RosterUndoState } from "./rosterUndoModel";
import RosterPlayerDialog from "./RosterPlayerDialog";
import { detailsAccount } from "./detailsNavigation";
import {
  staffDetailsEvent,
  type StaffDetailsRequest,
} from "./staffDetailsRequest";

/** One host across all staff rows: switching rows never stacks panels. */
export default function StaffDetailsHost() {
  const [request, setRequest] = useState<StaffDetailsRequest | null>(null);
  const [snapshot, setSnapshot] = useState<RosterSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [undo, setUndo] = useState<RosterUndoState | null>(null);
  const receipt = useRef<RosterSnapshot["undo"]>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  useEffect(() => {
    const open = (event: Event) =>
      setRequest((event as CustomEvent<StaffDetailsRequest>).detail);
    window.addEventListener(staffDetailsEvent, open);
    const tag = detailsAccount(),
      seasonId = new URLSearchParams(location.search).get("season");
    if (tag && seasonId && location.pathname !== "/cwl/roster")
      setRequest({
        tag,
        seasonId,
        viewOnly: location.pathname.includes("declaration")
          ? "declaration"
          : undefined,
      });
    return () => {
      generation.current++;
      window.removeEventListener(staffDetailsEvent, open);
    };
  }, []);
  useEffect(() => {
    if (!request) return;
    const id = ++generation.current;
    setBusy(true);
    setError("");
    void api<RosterSnapshot>(
      `/seasons/${encodeURIComponent(request.seasonId)}/roster`,
    )
      .then((result) => {
        if (id !== generation.current) return;
        if (!result.accounts.some((a) => a.tag === request.tag))
          throw new Error(
            "This account is no longer signed up in this season.",
          );
        setSnapshot(result);
      })
      .catch((cause) => {
        if (id === generation.current)
          setError(
            cause instanceof Error ? cause.message : "Could not load account.",
          );
      })
      .finally(() => {
        if (id === generation.current) setBusy(false);
      });
    return () => {
      generation.current++;
    };
  }, [request?.seasonId]);
  useEffect(() => {
    request?.onOpenChange?.(true);
    return () => request?.onOpenChange?.(false);
  }, [request?.onOpenChange]);
  useEffect(() => {
    request?.onBusy?.(busy);
    return () => request?.onBusy?.(false);
  }, [busy, request?.onBusy]);
  async function write(
    remove: boolean,
    body: Record<string, unknown> = {},
    pool?: Pool,
  ) {
    if (!request || !snapshot || busy || pending.current) return false;
    const id = generation.current;
    pending.current = true;
    setBusy(true);
    setError("");
    const path = `/seasons/${encodeURIComponent(request.seasonId)}`;
    try {
      await api(
        pool
          ? `${path}/staff-signup-changes`
          : `${path}/${remove ? "staff-signups" : "roster"}/${encodeURIComponent(request.tag)}`,
        pool ? "POST" : remove ? "DELETE" : "PATCH",
        pool
          ? { revision: snapshot.revision, tags: [request.tag], action: pool }
          : { revision: snapshot.revision, ...body },
      );
      if (id !== generation.current) return false;
      const latest = await api<RosterSnapshot>(`${path}/roster`);
      if (id !== generation.current) return false;
      setSnapshot(latest);
      if (!pool && !remove && ("assigned_clan_tag" in body || "kept" in body)) {
        receipt.current = latest.undo;
        setUndo(
          latest.undo
            ? { status: "available", label: latest.undo.label }
            : { status: "unavailable", message: "Undo no longer available" },
        );
      } else {
        receipt.current = null;
        setUndo(null);
      }
      await request.onChanged?.();
      return true;
    } catch (cause) {
      if (id === generation.current) {
        setError(
          cause instanceof Error ? cause.message : "Could not save account.",
        );
        if (cause instanceof ApiError && [401, 403].includes(cause.status))
          setSnapshot(null);
      }
      return false;
    } finally {
      pending.current = false;
      if (id === generation.current) setBusy(false);
    }
  }
  async function undoPlacement() {
    if (!request || !snapshot || !receipt.current || pending.current || busy)
      return;
    const id = generation.current,
      saved = receipt.current;
    pending.current = true;
    setBusy(true);
    setUndo({ status: "pending", label: saved.label });
    try {
      const path = `/seasons/${encodeURIComponent(request.seasonId)}/roster`;
      await api(`${path}/undo`, "POST", {
        revision: snapshot.revision,
        undo_id: saved.id,
      });
      const latest = await api<RosterSnapshot>(path);
      if (id === generation.current) {
        setSnapshot(latest);
        setUndo(null);
        receipt.current = null;
        await request.onChanged?.();
      }
    } catch {
      if (id === generation.current) {
        receipt.current = null;
        setUndo({
          status: "unavailable",
          message:
            "Undo no longer available. Refresh before making another change.",
        });
      }
    } finally {
      pending.current = false;
      if (id === generation.current) setBusy(false);
    }
  }
  const account = snapshot?.accounts.find((a) => a.tag === request?.tag);
  const order = request?.order || [];
  const index = order.indexOf(request?.tag || "");
  return (
    <>
      {request && !account && (
        <div role="status">
          {error || "Loading account details…"}
          <button
            onClick={() => {
              setRequest(null);
              setSnapshot(null);
            }}
          >
            Close
          </button>
        </div>
      )}
      {request && snapshot && account && (
        <RosterPlayerDialog
          account={account}
          clans={snapshot.clans}
          roster={snapshot}
          undo={
            undo && (
              <RosterUndoToast
                state={undo}
                onUndo={() => void undoPlacement()}
                onDismiss={() => setUndo(null)}
              />
            )
          }
          onPoolChange={(pool) => write(false, {}, pool)}
          busy={busy}
          error={error}
          onDirty={request.onDirty}
          previous={
            index > 0
              ? () => setRequest({ ...request, tag: order[index - 1] })
              : undefined
          }
          next={
            index >= 0 && index < order.length - 1
              ? () => setRequest({ ...request, tag: order[index + 1] })
              : undefined
          }
          onClose={() => {
            setRequest(null);
            setSnapshot(null);
            request.trigger?.focus({ preventScroll: true });
          }}
          onSave={(body) => write(false, body)}
          onRemove={() => write(true)}
        />
      )}
    </>
  );
}
