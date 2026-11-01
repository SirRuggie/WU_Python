import { mergeRosterMarks } from "./roster";
import {
  useEffect,
  useRef,
  useState,
  type Dispatch,
  type SetStateAction,
} from "react";
import { api, ApiError, type Pool } from "./api";
import type { RosterSnapshot } from "./roster";
import RosterUndoToast from "./RosterUndoToast";
import type { RosterUndoState } from "./rosterUndoModel";
import RosterPlayerDialog from "./RosterPlayerDialog";
import type { StaffDetailsRequest } from "./staffDetailsRequest";

export default function StaffDetailsPanel({
  archived = false,
  request,
  setRequest,
}: {
  archived?: boolean;
  request: StaffDetailsRequest;
  setRequest: Dispatch<SetStateAction<StaffDetailsRequest | null>>;
}) {
  const [snapshot, setSnapshot] = useState<RosterSnapshot | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [undo, setUndo] = useState<RosterUndoState | null>(null);
  const receipt = useRef<RosterSnapshot["undo"]>(null);
  const generation = useRef(0);
  const pending = useRef(false);
  useEffect(() => {
    if (!request) return;
    if (request.viewOnly === "declaration" && request.publishedSnapshot) {
      setSnapshot(request.publishedSnapshot.roster);
      setBusy(false);
      setError("");
      return;
    }
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
  }, [request?.seasonId, request?.publishedSnapshot]);
  useEffect(() => {
    request?.onBusy?.(busy);
    return () => request?.onBusy?.(false);
  }, [busy, request?.onBusy]);
  async function write(
    remove: boolean,
    body: Record<string, unknown> = {},
    pool?: Pool,
  ) {
    if (!request || request.viewOnly || !snapshot || busy || pending.current)
      return false;
    const id = generation.current;
    pending.current = true;
    setBusy(true);
    setError("");
    const path = `/seasons/${encodeURIComponent(request.seasonId)}`;
    let saved = false;
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
      saved = true;
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
        if (saved) {
          setError(
            "Saved. Couldn't refresh. Refresh the page to see the latest.",
          );
          receipt.current = null;
          setUndo(null);
          await Promise.resolve(request.onChanged?.()).catch(() => {});
          return true;
        }
        setError(
          cause instanceof ApiError &&
            cause.status === 409 &&
            "manual_weight" in body
            ? "Changed by someone else · Reload"
            : cause instanceof Error
              ? cause.message
              : "Could not save account.",
        );
        if (
          cause instanceof ApiError &&
          [401, 403, 409].includes(cause.status)
        ) {
          if (cause.status !== 409 || !("manual_weight" in body))
            setSnapshot(null);
          if (cause.status === 409 && !("manual_weight" in body)) {
            try {
              const latest = await api<RosterSnapshot>(`${path}/roster`);
              if (id === generation.current) setSnapshot(latest);
            } catch {
              // Keep the stale editor closed; the visible error remains discoverable.
            }
          }
        }
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
      const restored = await api<{
        tag?: string;
        roster_filler?: boolean;
        mark_revision?: number;
      }>(`${path}/undo`, "POST", {
        revision: snapshot.revision,
        undo_id: saved.id,
      });
      const latest = await api<RosterSnapshot>(path);
      if (id === generation.current) {
        setSnapshot((previous) =>
          request.viewOnly === "declaration" && previous
            ? mergeRosterMarks(
                previous,
                latest,
                restored.tag ? { ...restored, tag: restored.tag } : undefined,
              )
            : latest,
        );
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
          seasonId={request.seasonId}
          onFillerChanged={async (saved) => {
            if (!saved) {
              setSnapshot(null);
              await request.onChanged?.();
              return;
            }
            const id = generation.current;
            const latest = await api<RosterSnapshot>(
              `/seasons/${encodeURIComponent(request.seasonId)}/roster`,
            );
            if (id !== generation.current) return;
            setSnapshot((previous) =>
              previous
                ? mergeRosterMarks(previous, latest, {
                    tag: request.tag,
                    ...saved,
                  })
                : latest,
            );
            receipt.current = saved?.undo || null;
            setUndo(
              saved?.undo
                ? { status: "available", label: saved.undo.label }
                : null,
            );
            request.onChanged?.();
          }}
          account={account}
          archived={archived || request.archived}
          viewOnly={request.viewOnly}
          publicationNote={
            request.viewOnly === "declaration" &&
            request.publishedSnapshot &&
            !request.publishedSnapshot.signupTags.includes(request.tag)
              ? `No longer signed up · removed after version ${request.publishedSnapshot.version}`
              : undefined
          }
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
          onReload={async () => {
            const id = generation.current;
            const latest = await api<RosterSnapshot>(
              `/seasons/${encodeURIComponent(request.seasonId)}/roster`,
            );
            if (id === generation.current) {
              setSnapshot((previous) =>
                request.viewOnly === "declaration" && previous
                  ? {
                      ...previous,
                      revision: latest.revision,
                      accounts: previous.accounts.map((a) => {
                        const current = latest.accounts.find(
                          (x) => x.tag === a.tag,
                        );
                        return {
                          ...a,
                          roster_filler: current?.roster_filler,
                          roster_filler_revision:
                            current?.roster_filler_revision,
                        };
                      }),
                    }
                  : latest,
              );
              if (latest.undo && latest.undo.revision === latest.revision) {
                receipt.current = latest.undo;
                setUndo({ status: "available", label: latest.undo.label });
              }
              request.onChanged?.();
              setError("");
            }
          }}
          onSave={(body) => write(false, body)}
          onRemove={() => write(true)}
        />
      )}
    </>
  );
}
