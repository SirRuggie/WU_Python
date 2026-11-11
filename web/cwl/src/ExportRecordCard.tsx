import type { ReactNode } from "react";
import AccountCard from "./AccountCard";
import CardTally from "./CardTally";
import { StatusPill } from "./rosterUi/primitives";
import {
  syncStatusLabel,
  type ParticipationDisplayStatus,
} from "./participation";
import {
  bonusSelectionReason,
  bonusSelectionStatus,
  exportDateText,
  exportMonthLabel,
  exportWeightLabel,
  rosterResultSummary,
  type ExportRow,
} from "./exportPreview";

export type ExportKind =
  | "accounts"
  | "participation"
  | "participation-history"
  | "bonus-history";

const text = (value: unknown) =>
  value === null || value === undefined || value === "" ? "" : String(value);
const count = (value: unknown) =>
  typeof value === "number" ? value : text(value) || "—";
const poolLabel = (row: ExportRow) =>
  row.pool === "main" ? "Main CWL" : row.pool === "lazy" ? "Lazy CWL" : "";
const captureLabel = (row: ExportRow, prefix: string) =>
  (row[`${prefix}display_status`] as ParticipationDisplayStatus | undefined)
    ?.label ||
  syncStatusLabel(row[`${prefix}source_status`] as string | null | undefined);

/** Results for this roster: the tally, or the reason there is none. */
function rosterResult(row: ExportRow, prefix: string) {
  const unrecorded =
    row[`${prefix}matches_roster`] === false ||
    ((row[`${prefix}attacks`] ?? null) === null &&
      (row[`${prefix}stars`] ?? null) === null);
  return unrecorded
    ? { values: undefined, flag: rosterResultSummary(row, prefix) }
    : {
        values: (
          <CardTally
            attacks={count(row[`${prefix}attacks`])}
            stars={count(row[`${prefix}stars`])}
          />
        ),
        flag: null,
      };
}

/** One export preview row, in the same card as Results & participation. */
export default function ExportRecordCard({
  kind,
  row,
}: {
  kind: ExportKind;
  row: ExportRow;
}) {
  const th = typeof row.town_hall === "number" ? row.town_hall : null;
  const identity = [th !== null ? <>TH {th}</> : null, text(row.tag)];
  let meta: ReactNode[] = [];
  let values: ReactNode = undefined;
  let status: { tone: "neutral"; content: ReactNode } | undefined;
  let flags: ReactNode[] = [];
  let details: ReactNode = null;

  if (kind === "bonus-history") {
    const voided = !!row.voided_at;
    meta = [
      ...identity,
      text(row.clan_name) || text(row.clan_tag),
      `CWL month ${exportMonthLabel(row.cycle as string | null | undefined)}`,
    ];
    status = {
      tone: "neutral",
      content: (
        <StatusPill tone={voided ? "neutral" : "success"}>
          {bonusSelectionStatus(row)}
        </StatusPill>
      ),
    };
    flags = [
      row.confirmed_at
        ? `Selected on ${exportDateText(String(row.confirmed_at))}`
        : null,
      bonusSelectionReason(row) !== "—" ? bonusSelectionReason(row) : null,
    ];
  } else {
    meta = [
      ...identity,
      poolLabel(row),
      text(row.assigned_clan_name) || text(row.assigned_clan_tag),
    ];
    if (kind === "participation-history") {
      values = (
        <CardTally attacks={count(row.attacks)} stars={count(row.stars)} />
      );
      flags = [`Clash capture: ${captureLabel(row, "")}`];
      if (row.notes || row.updated_at)
        details = (
          <details className="export-record-details">
            <summary>Saved details</summary>
            {Boolean(row.updated_at) && (
              <p>Last saved {exportDateText(String(row.updated_at))}</p>
            )}
            {Boolean(row.notes) && <p>{String(row.notes)}</p>}
          </details>
        );
    } else {
      const prefix = kind === "accounts" ? "participation_" : "";
      const result = rosterResult(row, prefix);
      values = result.values;
      flags = [
        result.flag,
        kind === "accounts"
          ? `Weight ${exportWeightLabel(row.effective_weight)}`
          : `Clash capture: ${captureLabel(row, "")}`,
      ];
    }
  }

  return (
    <AccountCard
      className="export-record account-card-plain"
      thLevel={th}
      name={text(row.player_name) || "—"}
      meta={meta}
      values={values}
      status={status}
      flags={flags}
    >
      {details}
    </AccountCard>
  );
}
