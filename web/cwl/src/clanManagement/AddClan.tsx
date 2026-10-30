import { useRef, useState } from "react";
import { api } from "../api";
import ConfirmDialog from "../ConfirmDialog";
import type { Clan } from "./types";

type Lookup =
  | { state: "existing"; clan: Clan }
  | {
      state: "found" | "removed";
      tag: string;
      name: string;
      members: number;
      removal_id: string | null;
      reminder_revision: string | null;
    };

export default function AddClan({
  disabled,
  onBusy,
  onOpen,
}: {
  disabled: boolean;
  onBusy: (value: boolean) => void;
  onOpen: (clan: Clan, warning: string) => void;
}) {
  const [tag, setTag] = useState("");
  const [found, setFound] = useState<Lookup | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [confirm, setConfirm] = useState<"restore" | "fresh" | null>(null);
  const running = useRef(false);
  async function run(action: () => Promise<void>) {
    if (running.current || disabled) return;
    running.current = true;
    setBusy(true);
    onBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not update clan.");
    } finally {
      running.current = false;
      setBusy(false);
      onBusy(false);
    }
  }
  function lookup() {
    void run(async () => {
      setFound(null);
      const result = await api<Lookup>(
        `/manage/clans/${encodeURIComponent(tag.trim())}/lookup`,
      );
      setFound(result);
    });
  }
  function add(mode?: "fresh" | "restore") {
    if (!found || found.state === "existing") return;
    const snapshot = found;
    setConfirm(null);
    void run(async () => {
      if (mode === "restore") {
        const result = await api<{ clan: Clan; message: string }>(
          `/manage/clan-history/${encodeURIComponent(snapshot.removal_id!)}/restore`,
          "POST",
          { confirm_tag: snapshot.tag },
        );
        onOpen(result.clan, result.message);
      } else {
        const result = await api<{ clan: Clan; warning: string }>(
          "/manage/clans",
          "POST",
          {
            tag: snapshot.tag,
            ...(mode === "fresh"
              ? {
                  mode,
                  removal_id: snapshot.removal_id,
                  reminder_revision: snapshot.reminder_revision,
                }
              : {}),
          },
        );
        onOpen(result.clan, result.warning);
      }
    });
  }
  return (
    <section className="card clan-add" aria-label="Add a family clan">
      <form
        onSubmit={(e) => {
          e.preventDefault();
          lookup();
        }}
      >
        <label>
          Clan tag
          <input
            required
            placeholder="#CLANTAG"
            disabled={disabled || busy}
            value={tag}
            onChange={(e) => {
              setTag(e.target.value);
              setFound(null);
              setConfirm(null);
            }}
          />
        </label>
        <button disabled={disabled || busy}>
          {busy ? "Working…" : "Look up clan"}
        </button>
      </form>
      {error && (
        <p role="alert" className="notice error">
          {error}
        </p>
      )}
      {found?.state === "existing" ? (
        <p>
          Already in the family · {found.clan.name}{" "}
          <button
            disabled={disabled || busy}
            onClick={() => onOpen(found.clan, "")}
          >
            Open
          </button>
        </p>
      ) : (
        found && (
          <>
            <p>
              Found: {found.name} · {found.members} members
            </p>
            {found.state === "removed" ? (
              <div className="clan-tabs">
                <button
                  disabled={disabled || busy}
                  onClick={() => setConfirm("restore")}
                >
                  Restore old settings
                </button>
                <button
                  disabled={disabled || busy}
                  onClick={() => setConfirm("fresh")}
                >
                  Start fresh
                </button>
              </div>
            ) : (
              <button disabled={disabled || busy} onClick={() => add()}>
                Add
              </button>
            )}
          </>
        )
      )}
      {confirm && found && found.state !== "existing" && (
        <ConfirmDialog
          text={
            confirm === "fresh"
              ? `Start fresh for ${found.name}? This clears its previous clan and reminder settings. Delivery history is kept.`
              : `Restore old settings for ${found.name}? Review its roles, channels and artwork after restoring.`
          }
          confirmLabel={
            confirm === "fresh" ? "Start fresh" : "Restore old settings"
          }
          onConfirm={() => add(confirm)}
          onCancel={() => setConfirm(null)}
        />
      )}
    </section>
  );
}
