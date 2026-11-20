import { searchInputProps } from "./inputProps";
import { RefreshButton } from "./RefreshControl";
import { useDashboardPermission } from "./DashboardPermissions";
import { usesClanWeights } from "./clanWeightPolicy";
import { useEffect, useRef, useState, type ReactNode } from "react";
import SectionTabs from "./SectionTabs";
import ListToolbar from "./rosterUi/ListToolbar";
import SortTrigger from "./rosterUi/SortTrigger";
import ActionPanel from "./ActionPanel";
import { Button } from "./rosterUi/primitives";
import { compactWeightState } from "./CompactWeightField";
import type { ManualWeightDraft } from "./manualWeight";
import type { RosterAccount } from "./roster";
import WeightQueueRow from "./WeightQueueRow";
import "./WeightQueue.css";

type Props = {
  toolbarActions?: ReactNode;
  onOrderChange?: (tags: string[]) => void;
  onClanWeights?: (player?: string, clan?: string) => void;
  onDirty?: (dirty: boolean) => void;
  onDirtyCount?: (count: number) => void;
  resetToken?: number;
  accounts: RosterAccount[];
  busy: boolean;
  archived?: boolean;
  onEdit: (tag: string) => void;
  onSave: (tag: string, weight: number) => Promise<boolean>;
  onRefresh: () => void;
};
const emptyDraft: ManualWeightDraft = { unit: "loot", text: "" };

export default function WeightQueue({
  toolbarActions,
  accounts,
  onOrderChange,
  onClanWeights,
  busy,
  archived = false,
  onEdit,
  onSave,
  onRefresh,
  onDirty,
  onDirtyCount,
  resetToken,
}: Props) {
  const [search, setSearch] = useState("");
  const [scope, setScope] = useState<"all" | "main" | "lazy">("all");
  const [sort, setSort] = useState<"th" | "name" | "pool">("th");
  const [sortOpen, setSortOpen] = useState(false);
  const sortTrigger = useRef<HTMLButtonElement>(null);
  const sortLabels = { th: "Highest TH first", name: "Name A–Z", pool: "Pool" };
  const [permissionNotice, setPermissionNotice] = useState(false);
  const [limit, setLimit] = useState(50);
  const [drafts, setDrafts] = useState<Record<string, ManualWeightDraft>>({});
  const [unit, setUnit] = useState<ManualWeightDraft["unit"]>("loot");
  const previousResetToken = useRef(resetToken);
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
  const scoped = missing.filter(
    (account) => scope === "all" || account.pool === scope,
  );
  const matching = scoped
    .filter((account) =>
      `${account.player_name} ${account.tag}`
        .toLocaleLowerCase()
        .includes(query),
    )
    .sort(
      (a, b) =>
        Number(usesClanWeights(b)) - Number(usesClanWeights(a)) ||
        (sort === "th"
          ? (b.town_hall ?? 0) - (a.town_hall ?? 0)
          : sort === "pool"
            ? a.pool.localeCompare(b.pool)
            : 0) ||
        a.player_name.localeCompare(b.player_name) ||
        a.tag.localeCompare(b.tag),
    );
  const shown = matching.slice(0, limit);
  const orderKey = matching.map((account) => account.tag).join("|");
  useEffect(() => {
    onOrderChange?.(orderKey ? orderKey.split("|") : []);
  }, [orderKey, onOrderChange]);
  const canWeight = useDashboardPermission("clan_weights");
  const disabled = busy || saving || archived;
  const dirtyCount = missing.filter(
    (account) => !!drafts[account.tag]?.text.trim(),
  ).length;
  const dirty = dirtyCount > 0;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  useEffect(() => {
    onDirty?.(dirty);
    onDirtyCount?.(dirtyCount);
    return () => {
      onDirty?.(false);
      onDirtyCount?.(0);
    };
  }, [dirty, dirtyCount, onDirty, onDirtyCount]);
  useEffect(() => {
    if (previousResetToken.current === resetToken) return;
    previousResetToken.current = resetToken;
    setDrafts({});
    setErrors({});
    setFocusTarget(null);
  }, [resetToken]);
  useEffect(() => {
    if (disabled || focusTarget === null) return;
    (inputs.current.get(focusTarget) || searchInput.current)?.focus();
    setFocusTarget(null);
  }, [disabled, focusTarget, accounts]);

  async function save(account: RosterAccount) {
    if (disabled || !canWeight || pending.current || usesClanWeights(account))
      return;
    const state = compactWeightState({
      ...(drafts[account.tag] || emptyDraft),
      unit,
    });
    if (state.weight === null || state.error) return;
    const index = matching.findIndex((item) => item.tag === account.tag);
    const next = [
      ...matching.slice(index + 1),
      ...matching.slice(0, index).reverse(),
    ].find((item) => !usesClanWeights(item));
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
            "Weight was not saved. Check the message above and try again.",
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
        <h2 id="weight-queue-title">Needs weight · {scoped.length}</h2>
        <RefreshButton
          busy={busy || saving}
          disabled={archived}
          onRefresh={onRefresh}
          label="Refresh weights"
        />
      </div>
      {permissionNotice && (
        <p role="status">
          Permission needed: changing weights needs Clan weights access. Ask an
          owner.
        </p>
      )}
      <label className="weight-queue-search">
        <span className="sr-only">Find account</span>
        <input
          {...searchInputProps}
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
      <ListToolbar
        className="weight-queue-toolbar"
        scope={
          <SectionTabs
            mode="segmented"
            label="Missing weight pool"
            items={[
              { id: "all", label: "All" },
              { id: "main", label: "Main" },
              { id: "lazy", label: "Lazy" },
            ]}
            value={scope}
            onChange={(next) => {
              setScope(next);
              setLimit(50);
            }}
            disabled={busy || saving}
          />
        }
        sort={
          <SortTrigger
            ref={sortTrigger}
            label={sortLabels[sort]}
            aria-expanded={sortOpen}
            disabled={busy || saving}
            onClick={() => setSortOpen(true)}
          />
        }
        actions={toolbarActions}
      />
      {sortOpen && (
        <ActionPanel
          title="Sort missing weights"
          trigger={sortTrigger.current}
          className="roster-ui"
          onClose={() => setSortOpen(false)}
        >
          {(Object.keys(sortLabels) as (keyof typeof sortLabels)[]).map(
            (key) => (
              <Button
                key={key}
                aria-pressed={sort === key}
                onClick={() => {
                  setSort(key);
                  setLimit(50);
                  setSortOpen(false);
                }}
              >
                {sortLabels[key]}
              </Button>
            ),
          )}
        </ActionPanel>
      )}
      {!!missing.length && (
        <div
          className="weight-queue-unit-picker"
          role="group"
          aria-label="Enter weights as"
        >
          <span>Enter weights as:</span>
          <div className="weight-queue-unit-buttons">
            {(["loot", "full"] as const).map((option) => (
              <Button
                key={option}
                aria-pressed={unit === option}
                disabled={disabled}
                onClick={() => setUnit(option)}
              >
                {option === "loot" ? "Loot" : "Full"}
              </Button>
            ))}
          </div>
        </div>
      )}
      <div className="weight-queue-help">Saving does not move players.</div>
      {accounts.some((account) => account.current_fwa_status === "stale") && (
        <p role="status">
          Clan membership could not be checked. Showing last known groups.
        </p>
      )}
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
            <div role="status">No missing-weight accounts match this view.</div>
          )}
          {([true, false] as const).map((fwa) => (
            <div key={String(fwa)}>
              {shown.some((account) => usesClanWeights(account) === fwa) && (
                <h3>
                  {fwa
                    ? "FWA players · set in Clan weights ›"
                    : "Non-FWA accounts"}
                </h3>
              )}
              {shown
                .filter((account) => usesClanWeights(account) === fwa)
                .map((account) => (
                  <WeightQueueRow
                    key={account.tag}
                    account={account}
                    onClanWeights={onClanWeights}
                    value={{ ...(drafts[account.tag] || emptyDraft), unit }}
                    onChange={(value) => {
                      setDrafts((current) => ({
                        ...current,
                        [account.tag]: value,
                      }));
                      setErrors((current) => ({
                        ...current,
                        [account.tag]: "",
                      }));
                    }}
                    disabled={disabled || !canWeight}
                    busy={busy || saving}
                    onEdit={(tag) => {
                      if (!canWeight) setPermissionNotice(true);
                      else onEdit(tag);
                    }}
                    onSave={() => void save(account)}
                    error={errors[account.tag]}
                    inputRef={(node) => {
                      if (node) inputs.current.set(account.tag, node);
                      else inputs.current.delete(account.tag);
                    }}
                  />
                ))}
            </div>
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
