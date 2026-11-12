import CwlPageHeader from "./CwlPageHeader";
import RosterMenu from "./rosterUi/Menu";
import { fetchReadWithRetry } from "./readRetry";
import { useEffect, useRef, useState } from "react";
import { api, ApiError, type Season } from "./api";
import ExportRosterView from "./ExportRosterView";
import ExportWinnersView from "./ExportWinnersView";
import {
  monthSeasons,
  seasonMonthLabel,
  type ExportKind,
} from "./exportHistory";
import { useDashboardPermission } from "./DashboardPermissions";
import "./ExportWorkspace.css";
import { exportDateText as dateText } from "./exportPreview";

type Kind = ExportKind;
type Basis = "current" | "published";
type PreviewRow = Record<string, unknown>;
type ExportPreview = {
  kind: Kind;
  basis: Basis;
  summary: {
    season_label: string;
    season_status: string;
    cwl_month: string | null;
    published_version: number | null;
    published_at: string | null;
    published_available: boolean;
    roster_revision?: number | null;
  };
  columns: string[];
  rows: PreviewRow[];
  counts: { rows: number };
};
type Props = {
  seasonId: string;
  seasons: Season[];
  onSeasonChange: (id: string) => void;
};

const choices: { kind: Kind; label: string; description: string }[] = [
  {
    kind: "accounts",
    label: "Roster",
    description: "Saved accounts and hosting clans.",
  },
  {
    kind: "participation",
    label: "Signups",
    description: "Current signups and their results.",
  },
  {
    kind: "participation-history",
    label: "Results history",
    description: "Recorded results, including removed signups.",
  },
  {
    kind: "bonus-history",
    label: "Bonus winners",
    description: "Saved selections, not confirmed game awards.",
  },
];
const errorText = (cause: unknown) =>
  cause instanceof Error ? cause.message : "Could not load exports & history.";

export default function ExportWorkspace({
  seasonId,
  seasons,
  onSeasonChange,
}: Props) {
  const [kind, setKind] = useState<Kind>("accounts");
  const [basis, setBasis] = useState<Basis>("published");
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewFor, setPreviewFor] = useState("");
  const [publication, setPublication] = useState<{
    season: string;
    available: boolean;
  } | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState("");
  const [previewDenied, setPreviewDenied] = useState(false);
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [downloadError, setDownloadError] = useState("");
  const [downloadDenied, setDownloadDenied] = useState(false);
  const [notice, setNotice] = useState("");
  const [attempt, setAttempt] = useState(0);
  const canBonuses = useDashboardPermission("cwl_bonuses");
  const canSend = useDashboardPermission("cwl_send");
  const canBonusHistory = canBonuses || canSend;
  const previewRequest = useRef(0);
  const downloadController = useRef<AbortController | null>(null);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      previewRequest.current += 1;
      downloadController.current?.abort();
    };
  }, []);
  useEffect(() => {
    setPublication(null);
    setBasis("published");
  }, [seasonId]);
  useEffect(() => {
    downloadController.current?.abort();
    setDownloadBusy(false);
    setDownloadError("");
    setDownloadDenied(false);
    setNotice("");
  }, [seasonId, kind, basis, canBonusHistory]);
  useEffect(() => {
    const request = ++previewRequest.current;
    setPreview(null);
    setPreviewFor("");
    setPreviewError("");
    setPreviewDenied(false);
    if (!seasonId) {
      setPreviewLoading(false);
      return;
    }
    setPreviewLoading(true);
    if (kind === "bonus-history" && !canBonusHistory) {
      setPreviewLoading(false);
      setPreviewDenied(true);
      setPreviewError("You do not have access to this export.");
      return;
    }
    const read = (requested: Basis) =>
      api<ExportPreview>(
        `/seasons/${encodeURIComponent(seasonId)}/export-preview?${new URLSearchParams({ kind, basis: requested })}`,
      );
    // The existing current read supplies publication availability. Never render
    // working rows while a requested published snapshot is still being read.
    read("current")
      .then(async (current) => {
        if (request !== previewRequest.current) return;
        const available = current.summary.published_available;
        const archived = current.summary.season_status === "archived";
        const result =
          kind === "accounts" &&
          (basis === "published" || archived) &&
          available
            ? await read("published")
            : current;
        if (request !== previewRequest.current) return;
        setPublication({
          season: seasonId,
          available,
        });
        setPreview(
          kind === "accounts" && archived && !available
            ? { ...result, rows: [], counts: { rows: 0 } }
            : result,
        );
        setPreviewFor(
          `${seasonId}|${kind}|${kind === "accounts" ? basis : "current"}`,
        );
      })
      .catch((cause) => {
        if (request !== previewRequest.current) return;
        const denied =
          cause instanceof ApiError && [401, 403].includes(cause.status);
        setPreviewDenied(denied);
        setPreviewError(
          denied ? "You do not have access to this export." : errorText(cause),
        );
        if (denied) {
          setPreview(null);
          setPublication(null);
        }
      })
      .finally(() => {
        if (request === previewRequest.current) setPreviewLoading(false);
      });
    return () => {
      previewRequest.current += 1;
    };
  }, [seasonId, kind, basis, attempt, canBonusHistory]);

  const changeSeason = (id: string) => {
    downloadController.current?.abort();
    setPreview(null);
    setPublication(null);
    setBasis("published");
    onSeasonChange(id);
  };
  const changeKind = (next: Kind) => {
    downloadController.current?.abort();
    setPreview(null);
    setKind(next);
    setBasis("published");
  };
  const download = async () => {
    if (
      !seasonId ||
      (kind === "bonus-history" && !canBonusHistory) ||
      !displayedPreview ||
      rows.length === 0 ||
      previewLoading ||
      downloadBusy ||
      downloadController.current
    )
      return;
    const controller = new AbortController();
    downloadController.current = controller;
    setDownloadBusy(true);
    setDownloadError("");
    setDownloadDenied(false);
    setNotice("");
    const chosenBasis =
      kind === "accounts" && displayedPreview.summary.published_available
        ? displayedPreview.summary.season_status === "archived"
          ? "published"
          : basis
        : "current";
    try {
      const params = new URLSearchParams({ kind, basis: chosenBasis });
      const response = await fetchReadWithRetry(
        `/api/cwl/seasons/${encodeURIComponent(seasonId)}/export.csv?${params}`,
        {
          credentials: "same-origin",
          signal: controller.signal,
        },
      );
      if (controller.signal.aborted) return;
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        if (controller.signal.aborted) return;
        if (response.status === 401 || response.status === 403) {
          setPreview(null);
          window.dispatchEvent(new Event("dashboard-access-changed"));
        }
        throw new ApiError(body?.error || "Download failed.", response.status);
      }
      if (!response.headers.get("content-type")?.includes("text/csv"))
        throw new Error(
          "The server did not return a CSV file. Refresh the page and try again.",
        );
      const file = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(file);
      const link = document.createElement("a");
      link.href = url;
      link.download = `cwl-season-${seasonId}-${kind}-${chosenBasis}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("CSV download started. Check your browser downloads.");
    } catch (cause) {
      if (!controller.signal.aborted) {
        const denied =
          cause instanceof ApiError && [401, 403].includes(cause.status);
        setDownloadDenied(denied);
        setDownloadError(
          denied
            ? "You do not have access to this export."
            : "Download failed.",
        );
      }
    } finally {
      if (downloadController.current === controller)
        downloadController.current = null;
      if (mounted.current && !controller.signal.aborted) setDownloadBusy(false);
    }
  };

  const context = `${seasonId}|${kind}|${kind === "accounts" ? basis : "current"}`;
  const displayedPreview = previewFor === context ? preview : null;
  const currentPublication =
    publication?.season === seasonId ? publication : null;
  const publishedAvailable = currentPublication?.available === true;
  const rows = (displayedPreview?.rows || []).filter(
    (row) => kind !== "bonus-history" || !row.voided_at,
  );
  const effectiveBasis = publishedAvailable ? basis : "current";
  const selectedSeason = seasons.find(
    (season) => String(season.id) === seasonId,
  );

  return (
    <div className="export-workspace">
      <CwlPageHeader
        className="export-page-head"
        title={<h1>Exports &amp; history</h1>}
      >
        <RosterMenu
          label="Season"
          value={seasonId}
          disabled={downloadBusy}
          onValueChange={changeSeason}
          options={[
            { value: "", label: "Select a season" },
            ...monthSeasons(seasons).map((season) => ({
              value: String(season.id),
              label: seasonMonthLabel(season),
            })),
          ]}
        />
      </CwlPageHeader>
      {!seasonId && (
        <p className="export-empty">Select a season to review its data.</p>
      )}
      {seasonId && (
        <>
          <div className="export-controls">
            <label>
              Show
              <select
                name="export-show"
                value={kind}
                disabled={downloadBusy}
                onChange={(event) => changeKind(event.target.value as Kind)}
              >
                {choices
                  .filter(
                    (choice) =>
                      choice.kind !== "bonus-history" || canBonusHistory,
                  )
                  .map((choice) => (
                    <option key={choice.kind} value={choice.kind}>
                      {choice.label}
                    </option>
                  ))}
              </select>
            </label>
            {kind === "accounts" &&
              selectedSeason?.status !== "archived" &&
              currentPublication && (
                <div
                  className="export-roster-switch"
                  role="group"
                  aria-label="Roster basis"
                >
                  {(["published", "current"] as const).map((value) => (
                    <button
                      key={value}
                      type="button"
                      aria-pressed={effectiveBasis === value}
                      disabled={
                        downloadBusy ||
                        previewLoading ||
                        (value === "published" && !publishedAvailable)
                      }
                      onClick={() => {
                        if (value === effectiveBasis) return;
                        setPreview(null);
                        setBasis(value);
                      }}
                    >
                      {value === "published" ? "Published" : "Working"}
                    </button>
                  ))}
                </div>
              )}
            <p>{choices.find((choice) => choice.kind === kind)?.description}</p>
          </div>
          {previewLoading && <p role="status">Loading exports & history…</p>}
          {previewError && (
            <div className="notice error" role="alert">
              {previewError}
              {!previewDenied && (
                <button
                  type="button"
                  onClick={() => setAttempt((value) => value + 1)}
                >
                  Retry
                </button>
              )}
            </div>
          )}
          {downloadError && (
            <div className="notice error" role="alert">
              {downloadError}
              {!downloadDenied && (
                <button
                  type="button"
                  disabled={downloadBusy}
                  onClick={() => void download()}
                >
                  Retry
                </button>
              )}
            </div>
          )}
          {notice && (
            <div className="notice success" role="status">
              {notice}
            </div>
          )}
          {displayedPreview && !previewLoading && (
            <>
              <div className="export-ready">
                <div>
                  <strong>
                    {rows.length} {rows.length === 1 ? "account" : "accounts"}
                  </strong>
                  <span>
                    {kind === "accounts" &&
                    displayedPreview.summary.published_available &&
                    basis === "published"
                      ? `Published ${dateText(displayedPreview.summary.published_at)}`
                      : "Saved data for this month"}
                  </span>
                </div>
                <button
                  type="button"
                  className="primary"
                  disabled={downloadBusy || rows.length === 0}
                  onClick={() => void download()}
                >
                  {downloadBusy ? "Preparing CSV…" : "Download CSV"}
                </button>
              </div>
              {rows.some(
                (row) =>
                  kind === "participation" && row.matches_roster === false,
              ) && (
                <p className="export-mismatch-note">
                  Some results are blank (different clan). See Results history.
                </p>
              )}
              {kind === "accounts" && !publishedAvailable && (
                <p className="export-empty">
                  {selectedSeason?.status === "archived"
                    ? "No roster saved for this month."
                    : "Not published yet"}
                </p>
              )}
              {rows.length ? (
                kind === "bonus-history" ? (
                  <ExportWinnersView rows={rows} />
                ) : (
                  <ExportRosterView rows={rows} kind={kind} />
                )
              ) : (
                !(
                  kind === "accounts" &&
                  selectedSeason?.status === "archived" &&
                  !publishedAvailable
                ) && (
                  <p className="export-empty">
                    No saved accounts for this month.
                  </p>
                )
              )}
              <details className="export-about">
                <summary>CSV format &amp; data</summary>
                <p>
                  Blank results remain blank. Weights use full numbers; Discord
                  IDs remain complete. Names and notes are protected from
                  running as spreadsheet formulas. The file reflects saved data
                  at download time.
                </p>
              </details>
            </>
          )}
        </>
      )}
    </div>
  );
}
