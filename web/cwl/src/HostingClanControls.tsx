import { useEffect, useRef, useState } from "react";
import { Archive, Plus, Search } from "lucide-react";
import { api } from "./api";
import type { RosterClan } from "./roster";
import { useDashboardPermission } from "./DashboardPermissions";
import ActionPanel from "./ActionPanel";
import ConfirmDialog from "./ConfirmDialog";
import { Button, Input } from "./rosterUi/primitives";

type Choice = { tag: string; name: string };
export function availableFamily(clans: Choice[], hosts: RosterClan[]) {
  const existing = new Set(
    hosts.filter((item) => !item.archived).map((item) => item.tag),
  );
  return clans.filter((item) => !existing.has(item.tag));
}
export default function HostingClanControls({
  clans,
  onChanged,
  onBusy,
  onFamily,
  disabled,
}: {
  clans: RosterClan[];
  onChanged: () => Promise<void>;
  onBusy: (value: boolean) => void;
  onFamily?: () => void;
  disabled: boolean;
}) {
  const canSettings = useDashboardPermission("cwl_settings");
  const canRoster = useDashboardPermission("cwl_roster");
  const canSignups = useDashboardPermission("cwl_signups");
  const allowed = canSettings && (canRoster || canSignups);
  const familyAllowed = useDashboardPermission("clans");
  const [open, setOpen] = useState(false);
  const [mode, setMode] = useState<"family" | "tag">("family");
  const [family, setFamily] = useState<Choice[]>([]);
  const [search, setSearch] = useState("");
  const [tag, setTag] = useState("");
  const [choice, setChoice] = useState<Choice | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [familyLoading, setFamilyLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const generation = useRef(0),
    submitted = useRef(false);
  const trigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  useEffect(() => {
    let active = true;
    if (!open) return;
    setChoice(null);
    setError("");
    setFamilyLoading(true);
    void api<{ clans: Choice[] }>("/approved-clans")
      .then((result) => {
        if (active) setFamily(result.clans);
      })
      .catch((cause) => {
        if (active)
          setError(
            cause instanceof Error
              ? cause.message
              : "Could not load family clans.",
          );
      })
      .finally(() => {
        if (active) setFamilyLoading(false);
      });
    return () => {
      active = false;
      generation.current++;
    };
  }, [open]);
  async function lookup() {
    if (busy || disabled || !allowed) return;
    const id = ++generation.current;
    setLoading(true);
    setChoice(null);
    setError("");
    try {
      const result = await api<Choice>(
        `/clans/lookup?tag=${encodeURIComponent(tag.trim())}`,
      );
      if (id !== generation.current) return;
      if (clans.some((item) => item.tag === result.tag && !item.archived))
        throw new Error("This clan is already hosting.");
      setChoice(result);
    } catch (cause) {
      if (id === generation.current)
        setError(
          cause instanceof Error ? cause.message : "Could not find clan.",
        );
    } finally {
      if (id === generation.current) setLoading(false);
    }
  }
  async function add() {
    if (!choice || submitted.current || disabled || !allowed) return;
    submitted.current = true;
    setBusy(true);
    setError("");
    try {
      await api("/clans", "POST", { tag: choice.tag, pool: null });
      setNotice(`${choice.name} added as a hosting clan.`);
      setOpen(false);
      try {
        await onChanged();
      } catch {
        setError("Clan added. Refresh the roster to see it.");
      }
    } catch (cause) {
      setError(
        cause instanceof Error ? cause.message : "Could not add hosting clan.",
      );
    } finally {
      submitted.current = false;
      setBusy(false);
    }
  }
  if (!allowed) return null;
  const matches = availableFamily(family, clans).filter((item) =>
    `${item.name} ${item.tag}`
      .toLowerCase()
      .includes(search.trim().toLowerCase()),
  );
  return (
    <>
      <button
        ref={trigger}
        type="button"
        className="roster-ui roster-ui-button is-secondary"
        disabled={disabled || busy}
        onClick={() => {
          setMode("family");
          setSearch("");
          setTag("");
          setNotice("");
          setOpen(true);
        }}
      >
        <Plus size={18} aria-hidden="true" /> Add hosting clan
      </button>
      {notice && <p role="status">{notice}</p>}
      {!open && error && <p role="alert">{error}</p>}
      {open && (
        <ActionPanel
          title="Add hosting clan"
          className="roster-ui"
          trigger={trigger.current}
          busy={busy}
          onClose={() => {
            if (busy) return false;
            setOpen(false);
            return true;
          }}
          footer={
            <Button
              variant="primary"
              disabled={!choice || busy || disabled || loading}
              onClick={() => void add()}
            >
              Confirm add hosting clan
            </Button>
          }
        >
          <div className="workflow-tabs">
            <Button
              aria-pressed={mode === "family"}
              disabled={busy}
              onClick={() => {
                generation.current++;
                setLoading(false);
                setMode("family");
                setChoice(null);
                setError("");
              }}
            >
              From family clans
            </Button>
            <Button
              aria-pressed={mode === "tag"}
              disabled={busy}
              onClick={() => {
                generation.current++;
                setLoading(false);
                setMode("tag");
                setChoice(null);
                setError("");
              }}
            >
              By clan tag
            </Button>
          </div>
          {mode === "family" ? (
            <>
              <Input
                label="Search family clans"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {familyLoading ? (
                <p role="status">Loading family clans…</p>
              ) : (
                <div className="hosting-clan-choices">
                  {matches.map((item) => (
                    <Button
                      key={item.tag}
                      aria-pressed={choice?.tag === item.tag}
                      disabled={busy}
                      onClick={() => setChoice(item)}
                    >
                      {item.name} · {item.tag}
                    </Button>
                  ))}
                  {!matches.length && <p>No other family clans match.</p>}
                </div>
              )}
              {familyAllowed && onFamily && (
                <Button
                  disabled={busy}
                  onClick={() => {
                    setOpen(false);
                    onFamily();
                  }}
                >
                  Family clans are managed in Clan management ›
                </Button>
              )}
            </>
          ) : (
            <>
              <Input
                label="Clan tag"
                value={tag}
                disabled={busy}
                onChange={(event) => {
                  generation.current++;
                  setLoading(false);
                  setTag(event.target.value);
                  setChoice(null);
                  setError("");
                }}
                placeholder="#CLANTAG"
              />
              <Button
                icon={Search}
                disabled={!tag.trim() || busy || loading}
                onClick={() => void lookup()}
              >
                Look up clan
              </Button>
            </>
          )}
          {choice && (
            <p>
              <strong>{choice.name}</strong> · {choice.tag}
              <br />
              <span className="small">
                Confirm to add this hosting clan. Set its pool and rules next.
              </span>
            </p>
          )}
          {error && <p role="alert">{error}</p>}
        </ActionPanel>
      )}
    </>
  );
}

export function ArchiveHostingClan({
  clan,
  disabled,
  onChanged,
  onBusy,
}: {
  clan: RosterClan;
  disabled: boolean;
  onChanged: () => Promise<void>;
  onBusy: (value: boolean) => void;
}) {
  const canSettings = useDashboardPermission("cwl_settings");
  const canRoster = useDashboardPermission("cwl_roster");
  const canSignups = useDashboardPermission("cwl_signups");
  const allowed = canSettings && (canRoster || canSignups);
  const [confirm, setConfirm] = useState(false),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const submitted = useRef(false);
  useEffect(() => {
    onBusy(busy);
    return () => onBusy(false);
  }, [busy, onBusy]);
  async function archive() {
    if (!allowed || disabled || submitted.current) return;
    submitted.current = true;
    setBusy(true);
    setConfirm(false);
    setError("");
    try {
      await api(`/clans/${encodeURIComponent(clan.tag)}`, "PATCH", {
        archived: true,
      });
      await onChanged();
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not archive clan. Refresh before trying again.",
      );
    } finally {
      submitted.current = false;
      setBusy(false);
    }
  }
  if (!allowed) return null;
  return (
    <>
      <Button
        variant="danger"
        icon={Archive}
        disabled={disabled || busy}
        onClick={() => setConfirm(true)}
      >
        Archive hosting clan
      </Button>
      {error && <p role="alert">{error}</p>}
      {confirm && (
        <ConfirmDialog
          heading="Archive hosting clan"
          danger
          text={`Archive ${clan.name}? It won't host CWL in future seasons until you add it again. This season's assignments stay.`}
          confirmLabel="Archive clan"
          disabled={disabled || busy}
          onCancel={() => setConfirm(false)}
          onConfirm={() => void archive()}
        >
          <p>
            Archiving is global: new placements stop in every season. Existing
            assignments and history stay saved.
          </p>
        </ConfirmDialog>
      )}
    </>
  );
}
