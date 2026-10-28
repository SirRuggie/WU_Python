import HostingClanControls, { ArchiveHostingClan } from "./HostingClanControls";
import { compactRosterWeight } from "./rosterCompactWeight";
import {
  capacityState,
  rangeImpact,
  settingsWeight,
  weightKeystroke,
} from "./clanSettingsModel";
import { useEffect, useId, useRef, useState } from "react";
import { Check } from "lucide-react";
import type { Pool } from "./api";
import type { RosterAccount, RosterClan } from "./roster";
import { weightInputText } from "./roster";
import { comparisonWeightRange } from "./comparePresentation";
import {
  poolChangeReason,
  settingsClans,
  type ClanRules,
} from "./clanSettingsModel";
import ActionPanel from "./ActionPanel";
import RosterMenu from "./rosterUi/Menu";
import { Button, Input, ProgressBar } from "./rosterUi/primitives";
import "./RosterClanChips.css";
import "./ClanSettings.css";

type Props = {
  onHostingChanged?: () => Promise<void>;
  onHostingBusy?: (busy: boolean) => void;
  onFamily?: () => void;
  clans: RosterClan[];
  accounts?: RosterAccount[];
  pool: Pool;
  busy: boolean;
  archived: boolean;
  onPoolChange: (pool: Pool) => void;
  onDirty: (dirty: boolean) => void;
  onLeave: () => boolean;
  onSave: (clan: RosterClan, rules: ClanRules) => Promise<boolean>;
};

export default function ClanSettings(props: Props) {
  const [tag, setTag] = useState<string | null>(null);
  const [trigger, setTrigger] = useState<HTMLElement | null>(null);
  const [moved, setMoved] = useState<{
    tag: string;
    name: string;
    pool: Pool;
  } | null>(null);
  const [highlight, setHighlight] = useState<string | null>(null);
  const list = useRef<HTMLDivElement>(null);
  const clan = props.clans.find((item) => item.tag === tag && !item.archived);
  const visible = settingsClans(props.clans, props.pool);
  useEffect(() => {
    setTag(null);
  }, [props.pool]);
  useEffect(() => {
    if (!highlight) return;
    const row = Array.from(
      list.current?.querySelectorAll<HTMLButtonElement>("[data-clan]") || [],
    ).find((item) => item.dataset.clan === highlight);
    row?.scrollIntoView({ block: "nearest", behavior: "auto" });
    row?.focus({ preventScroll: true });
  }, [highlight, props.pool]);
  const close = () => {
    if (!props.onLeave()) return false;
    setTag(null);
    return true;
  };
  return (
    <section className="roster-ui clan-settings" aria-label="Clan settings">
      {props.onHostingChanged && props.onHostingBusy && !props.archived && <HostingClanControls clans={props.clans} onChanged={props.onHostingChanged} onBusy={props.onHostingBusy} onFamily={props.onFamily} disabled={props.busy || !!tag} />}
      {moved && (
        <div role="status" className="clan-settings-moved">
          {moved.name} moved to {moved.pool === "main" ? "Main" : "Lazy"} CWL ·{" "}
          <Button
            onClick={() => {
              props.onPoolChange(moved.pool);
              setHighlight(moved.tag);
              setMoved(null);
            }}
            disabled={props.busy}
          >
            View
          </Button>
          <Button aria-label="Dismiss message" onClick={() => setMoved(null)}>
            ×
          </Button>
        </div>
      )}
      <div ref={list} className="clan-settings-list">
        {props.archived && (
          <p className="clan-settings-archived">
            Archived season · settings are read-only.
          </p>
        )}
        {[null, props.pool].map((group) => {
          const rows = visible.filter((item) => item.pool === group);
          return rows.length ? (
            <div key={group || "unset"} className="clan-settings-group">
              {!group && <h3>Needs a pool</h3>}
              {rows.map((item) => (
                <Button
                  key={item.tag}
                  data-clan={item.tag}
                  className={`roster-clan-chip clan-settings-row is-${capacityState(item.assigned_count, item.capacity)}${highlight === item.tag ? " is-selected" : ""}`}
                  disabled={props.busy}
                  onClick={(event) => {
                    setTrigger(event.currentTarget);
                    setTag(item.tag);
                    setHighlight(null);
                    setMoved(null);
                  }}
                >
                  <span className="roster-clan-chip-content">
                    <span className="roster-clan-chip-top">
                      <strong>{item.name}</strong>
                      <span className="roster-clan-chip-count">
                        {item.assigned_count} / {item.capacity ?? "—"}
                        {item.capacity &&
                          item.assigned_count > item.capacity && (
                            <span className="clan-settings-over">
                              {" "}
                              · +{item.assigned_count - item.capacity} over
                            </span>
                          )}
                      </span>
                    </span>
                    <span className="clan-settings-description">
                      {item.pool && item.capacity
                        ? `${item.capacity}v${item.capacity} · ${comparisonWeightRange(item) || "Any weight"} · ${item.cwl_league || "League unavailable"}`
                        : "Not set up"}
                    </span>
                    {item.capacity && (
                      <ProgressBar
                        decorative
                        value={item.assigned_count}
                        max={item.capacity}
                        label={`${item.name} assigned accounts`}
                      />
                    )}
                  </span>
                </Button>
              ))}
            </div>
          ) : null;
        })}
        {!visible.length && <p>No hosting clans in this pool.</p>}
      </div>
      {clan && (
        <ClanSettingsEditor
          key={clan.tag}
          onArchiveChanged={props.onHostingChanged}
          onArchiveBusy={props.onHostingBusy}
          clan={clan}
          accounts={props.accounts || []}
          busy={props.busy}
          archived={props.archived}
          trigger={trigger}
          onClose={close}
          onDirty={props.onDirty}
          onSave={async (rules) => {
            const saved = await props.onSave(clan, rules);
            if (saved) {
              setTag(null);
              if (clan.pool !== rules.pool)
                setMoved({ tag: clan.tag, name: clan.name, pool: rules.pool });
            }
            return saved;
          }}
        />
      )}
    </section>
  );
}

export function ClanSettingsEditor({
  onArchiveChanged, onArchiveBusy,
  clan,
  accounts = [],
  busy,
  archived,
  trigger,
  onClose,
  onDirty,
  onSave,
}: {
  onArchiveChanged?: () => Promise<void>;
  onArchiveBusy?: (busy: boolean) => void;
  clan: RosterClan;
  accounts?: RosterAccount[];
  busy: boolean;
  archived: boolean;
  trigger: HTMLElement | null;
  onClose: () => boolean;
  onDirty: (dirty: boolean) => void;
  onSave: (rules: ClanRules) => Promise<boolean>;
}) {
  const values = () => ({
    pool: clan.pool && clan.capacity ? clan.pool : "",
    capacity: clan.pool && clan.capacity ? String(clan.capacity) : "",
    min: weightInputText(clan.min_weight),
    max: weightInputText(clan.max_weight),
  });
  const [base, setBase] = useState(values);
  const [draft, setDraft] = useState(values);
  const [error, setError] = useState("");
  const submitting = useRef(false);
  const unitId = useId();
  const changed = JSON.stringify(base) !== JSON.stringify(draft);
  const stale = JSON.stringify(base) !== JSON.stringify(values());
  const latest = () => {
    setBase(values());
    setDraft(values());
    setError("");
  };
  useEffect(() => {
    if (!changed && stale) latest();
  }, [clan, changed, stale]);
  useEffect(() => {
    onDirty(changed);
    return () => onDirty(false);
  }, [changed, onDirty]);
  const min = settingsWeight(draft.min),
    max = settingsWeight(draft.max);
  const rangeError =
    !min.error &&
    !max.error &&
    min.value !== null &&
    max.value !== null &&
    min.value >= max.value
      ? "Maximum weight must be greater than minimum weight."
      : "";
  const invalid = !!(min.error || max.error || rangeError);
  const poolError = draft.pool
    ? poolChangeReason(clan, draft.pool as Pool)
    : "";
  const rangeChanged = draft.min !== base.min || draft.max !== base.max;
  const oldOutside = rangeImpact(
    accounts,
    clan.tag,
    settingsWeight(base.min).value,
    settingsWeight(base.max).value,
  );
  const newOutside = rangeImpact(accounts, clan.tag, min.value, max.value);
  const impact =
    rangeChanged && !invalid
      ? newOutside.filter(
          (account) => !oldOutside.some((old) => old.tag === account.tag),
        )
      : [];
  const inside =
    rangeChanged && !invalid
      ? oldOutside.filter(
          (account) => !newOutside.some((next) => next.tag === account.tag),
        )
      : [];
  const capacity = draft.capacity ? Number(draft.capacity) : null;
  const count = (
    <p className="clan-settings-count">
      {clan.assigned_count} assigned
      {capacity && (
        <>
          {" "}
          · {capacity}v{capacity}
          {clan.assigned_count > capacity && (
            <span className="clan-settings-over">
              {" "}
              · +{clan.assigned_count - capacity} over
            </span>
          )}
        </>
      )}
    </p>
  );
  const submit = async () => {
    if (
      busy ||
      submitting.current ||
      archived ||
      stale ||
      !changed ||
      !draft.pool ||
      !draft.capacity ||
      invalid ||
      poolError
    )
      return;
    try {
      submitting.current = true;
      setError("");
      if (
        await onSave({
          pool: draft.pool as Pool,
          capacity: Number(draft.capacity),
          min_weight: min.value,
          max_weight: max.value,
        })
      )
        setBase(draft);
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Settings could not be saved.",
      );
    } finally {
      submitting.current = false;
    }
  };
  return (
    <ActionPanel
      title={`${clan.name} · ${clan.tag}`}
      trigger={trigger}
      onClose={onClose}
      busy={busy}
      className="roster-ui clan-settings-panel"
      footer={
        !archived && (
          <Button
            variant="primary"
            icon={Check}
            disabled={
              busy ||
              stale ||
              !changed ||
              !draft.pool ||
              !draft.capacity ||
              invalid ||
              !!poolError
            }
            onClick={() => void submit()}
          >
            {clan.pool && clan.capacity ? "Save settings" : "Set up clan"}
          </Button>
        )
      }
    >
      {archived ? (
        <>
          <p className="clan-settings-archived">
            Archived season · settings are read-only.
          </p>
          <dl>
            <dt>Pool</dt>
            <dd>
              {clan.pool
                ? `${clan.pool === "main" ? "Main" : "Lazy"} CWL`
                : "Not set up"}
            </dd>
            <dt>CWL war size</dt>
            <dd>
              {clan.capacity
                ? `${clan.capacity}v${clan.capacity}`
                : "Not set up"}
            </dd>
            <dt>Range</dt>
            <dd>{comparisonWeightRange(clan) || "Any weight"}</dd>
          </dl>
        </>
      ) : (
        <>
          <p className="clan-settings-description">
            Auto-place uses these settings. Existing assignments don't change.
          </p>
          <RosterMenu
            label="Pool"
            value={draft.pool}
            disabled={busy}
            onValueChange={(pool) => setDraft({ ...draft, pool })}
            options={(["main", "lazy"] as const).map((pool) => ({
              value: pool,
              label: `${pool === "main" ? "Main" : "Lazy"} CWL`,
              disabled: !!poolChangeReason(clan, pool),
              description: poolChangeReason(clan, pool),
            }))}
          />
          <RosterMenu
            label="CWL war size"
            value={draft.capacity}
            disabled={busy}
            onValueChange={(capacity) => setDraft({ ...draft, capacity })}
            options={[
              { value: "15", label: "15v15" },
              { value: "30", label: "30v30" },
            ]}
          />
          <span id={unitId} className="sr-only">
            Weights in thousands (k)
          </span>
          <div className="clan-settings-weights">
            <Input
              className="clan-settings-k-input"
              inputMode="decimal"
              error={min.error}
              label="Minimum weight"
              aria-describedby={unitId}
              value={draft.min}
              disabled={busy}
              onChange={(event) =>
                weightKeystroke(event.target.value) &&
                setDraft({ ...draft, min: event.target.value })
              }
            />
            <Input
              className="clan-settings-k-input"
              inputMode="decimal"
              error={max.error || rangeError}
              label="Maximum weight"
              aria-describedby={unitId}
              value={draft.max}
              disabled={busy}
              onChange={(event) =>
                weightKeystroke(event.target.value) &&
                setDraft({ ...draft, max: event.target.value })
              }
            />
          </div>
          {!invalid && (
            <div className="clan-settings-range" aria-live="polite">
              <p>
                Range:{" "}
                {comparisonWeightRange({
                  min_weight: min.value,
                  max_weight: max.value,
                }) || "Any weight"}
              </p>
              {min.value !== null && max.value !== null && (
                <small>
                  Includes {compactRosterWeight(min.value)}, up to just under{" "}
                  {compactRosterWeight(max.value)}.
                </small>
              )}
            </div>
          )}
          {count}
          {(impact.length > 0 || inside.length > 0) && (
            <details className="clan-settings-impact">
              <summary>
                {impact.length > 0 &&
                  `${impact.length} more assigned ${impact.length === 1 ? "player" : "players"} would be outside the range`}
                {impact.length > 0 && inside.length > 0 && " · "}
                {inside.length > 0 && `${inside.length} would move inside`}
              </summary>
              <ul>
                {impact.map((account) => (
                  <li key={account.tag}>
                    {account.player_name} ·{" "}
                    {compactRosterWeight(account.effective_weight)} · Would move
                    outside
                  </li>
                ))}
                {inside.map((account) => (
                  <li key={account.tag}>
                    {account.player_name} ·{" "}
                    {compactRosterWeight(account.effective_weight)} · Would move
                    inside
                  </li>
                ))}
              </ul>
            </details>
          )}
          {poolError && <p role="alert">{poolError}</p>}
          {error && <p role="alert">{error}</p>}
          {stale && changed && (
            <p role="alert">
              Clan settings changed elsewhere. Your edits are preserved.{" "}
              <Button disabled={busy} onClick={latest}>
                Discard edits and use latest settings
              </Button>
            </p>
          )}
        </>
      )}
      {!archived && onArchiveChanged && onArchiveBusy && <ArchiveHostingClan clan={clan} disabled={busy || changed} onChanged={onArchiveChanged} onBusy={onArchiveBusy} />}
    </ActionPanel>
  );
}
