import { useEffect, useRef, useState } from "react";
import { RefreshCw } from "lucide-react";
import { Button } from "./rosterUi/primitives";
import { compactWeightState } from "./CompactWeightField";
import type { ManualWeightDraft } from "./manualWeight";
import type { RosterAccount } from "./roster";
import WeightQueueRow from "./WeightQueueRow";
import "./WeightQueue.css";

type Props = {
  onClanWeights?: () => void;
  onDirty?: (dirty: boolean) => void;
  accounts: RosterAccount[];
  busy: boolean;
  archived?: boolean;
  onEdit: (tag: string) => void;
  onSave: (tag: string, weight: number) => Promise<boolean>;
  onRefresh: () => void;
};
const emptyDraft: ManualWeightDraft = { unit: "loot", text: "" };

export default function WeightQueue({
  accounts,
  onClanWeights,
  busy,
  archived = false,
  onEdit,
  onSave,
  onRefresh,
  onDirty,
}: Props) {
  const [search, setSearch] = useState("");
  const [limit, setLimit] = useState(50);
  const [drafts, setDrafts] = useState<Record<string, ManualWeightDraft>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [saving, setSaving] = useState(false);
  const pending = useRef(false);
  const mounted = useRef(true);
  const inputs = useRef(new Map<string, HTMLInputElement>());
  const searchInput = useRef<HTMLInputElement>(null);
  const [focusTarget, setFocusTarget] = useState<string | null>(null);
  const missing = accounts.filter(
    (account) => account.effective_weight === null,
  );
  const query = search.trim().toLocaleLowerCase();
  const matching = missing.filter((account) =>
    `${account.player_name} ${account.tag}`.toLocaleLowerCase().includes(query),
  );
  const shown = matching.slice(0, limit);
  const disabled = busy || saving || archived;
  const dirty = missing.some((account) => !!drafts[account.tag]?.text);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    onDirty?.(dirty);
    return () => onDirty?.(false);
  }, [dirty, onDirty]);
  useEffect(() => {
    if (disabled || focusTarget === null) return;
    (inputs.current.get(focusTarget) || searchInput.current)?.focus();
    setFocusTarget(null);
  }, [disabled, focusTarget, accounts]);

  async function save(account: RosterAccount) {
    if (disabled || pending.current || account.clan_weight_managed) return;
    const state = compactWeightState(drafts[account.tag] || emptyDraft);
    if (state.weight === null || state.error) return;
    const index = matching.findIndex((item) => item.tag === account.tag);
    const next = [
      ...matching.slice(index + 1),
      ...matching.slice(0, index).reverse(),
    ].find((item) => !item.clan_weight_managed);
    pending.current = true;
    setSaving(true);
    try {
      const saved = await onSave(account.tag, state.weight);
      if (!mounted.current) return;
      if (saved) {
        setDrafts((current) => {
          const copy = { ...current };
          delete copy[account.tag];
          return copy;
        });
        setFocusTarget(next?.tag || "");
      } else
        setErrors((current) => ({
          ...current,
          [account.tag]:
            "Weight wasn't saved. Check the message above and try again.",
        }));
    } catch (error) {
      if (mounted.current)
        setErrors((current) => ({
          ...current,
          [account.tag]:
            error instanceof Error
              ? error.message
              : "Weight could not be saved.",
        }));
    } finally {
      pending.current = false;
      if (mounted.current) setSaving(false);
    }
  }

  return (
    <section
      className="card roster-ui weight-queue"
      aria-labelledby="weight-queue-title"
    >
      <div className="weight-queue-heading">
        <h2 id="weight-queue-title">Needs weight · {missing.length}</h2>
        <Button icon={RefreshCw} disabled={disabled} onClick={onRefresh}>
          Refresh weights
        </Button>
      </div>
      <label className="weight-queue-search">
        <span className="sr-only">Find account</span>
        <input
          ref={searchInput}
          type="search"
          value={search}
          onChange={(event) => {
            setSearch(event.target.value);
            setLimit(50);
          }}
          placeholder="Name or player tag"
        />
      </label>
      <div className="weight-queue-help">
        Saving doesn't move anyone. Refresh keeps manual weights.
      </div>
      {archived && (
        <div className="weight-queue-help">Archived season · view only</div>
      )}
      {!missing.length ? (
        <div role="status">
          <h3>All accounts have a weight ✓</h3>
          <div className="weight-queue-help">
            Return to the roster to preview automatic placement.
          </div>
        </div>
      ) : (
        <>
          {!matching.length && (
            <div role="status">
              No missing-weight accounts match your search.
            </div>
          )}
          {shown.map((account) => (
            <WeightQueueRow
              key={account.tag}
              account={account}
              onClanWeights={onClanWeights}
              value={drafts[account.tag] || emptyDraft}
              onChange={(value) => {
                setDrafts((current) => ({ ...current, [account.tag]: value }));
                setErrors((current) => ({ ...current, [account.tag]: "" }));
              }}
              disabled={disabled}
              busy={busy || saving}
              onEdit={onEdit}
              onSave={() => void save(account)}
              error={errors[account.tag]}
              inputRef={(node) => {
                if (node) inputs.current.set(account.tag, node);
                else inputs.current.delete(account.tag);
              }}
            />
          ))}
          <div className="weight-queue-more">
            <span>
              Showing {shown.length} of {matching.length}
            </span>
            {shown.length < matching.length && (
              <Button
                disabled={busy || saving}
                onClick={() => setLimit((current) => current + 50)}
              >
                Load more
              </Button>
            )}
          </div>
        </>
      )}
    </section>
  );
}
