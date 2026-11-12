import { useEffect, useRef, useState } from "react";
import { ApiError, type Season } from "./api";
import { fetchReadWithRetry } from "./readRetry";
import { exportMonthLabel } from "./exportPreview";
import { seasonCycle, seasonMonthLabel } from "./exportHistory";

const MIME =
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
const monthsBetween = (from: string, to: string) => {
  if (
    !/^\d{4}-(0[1-9]|1[0-2])$/.test(from) ||
    !/^\d{4}-(0[1-9]|1[0-2])$/.test(to)
  )
    return 0;
  return (
    (Number(to.slice(0, 4)) - Number(from.slice(0, 4))) * 12 +
    Number(to.slice(5)) -
    Number(from.slice(5)) +
    1
  );
};
const rangeName = (from: string, to: string) => {
  const a = exportMonthLabel(from).split(" "),
    b = exportMonthLabel(to).split(" ");
  return `CWL ${a[0].slice(0, 3)}${a[1] === b[1] ? "" : ` ${a[1]}`}–${b[0].slice(0, 3)} ${b[1]}.xlsx`;
};

type Props = {
  seasonId: string;
  seasons: Season[];
  basis: "current" | "published";
  ready: boolean;
  canDownload: boolean;
  onDenied: () => void;
};
export default function ExportDownloads({
  seasonId,
  seasons,
  basis,
  ready,
  canDownload,
  onDenied,
}: Props) {
  const options = [...new Set(seasons.map(seasonCycle).filter(Boolean))].sort();
  const latest = options.at(-1) || "";
  const optionKey = options.join(",");
  const [from, setFrom] = useState(
    options.find((month) => monthsBetween(month, latest) <= 12) || latest,
  );
  const [to, setTo] = useState(latest);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [rangeError, setRangeError] = useState("");
  const [denied, setDenied] = useState(false);
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState<"season" | "range" | null>(null);
  const request = useRef<{
    controller: AbortController;
    kind: "season" | "range";
  } | null>(null);
  const mounted = useRef(true);
  useEffect(() => {
    const available = optionKey ? optionKey.split(",") : [];
    const last = available.at(-1) || "";
    setFrom((previous) =>
      available.includes(previous)
        ? previous
        : available.find((month) => monthsBetween(month, last) <= 12) || last,
    );
    setTo((previous) => (available.includes(previous) ? previous : last));
  }, [optionKey]);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      request.current?.controller.abort();
      request.current = null;
    };
  }, []);
  useEffect(() => {
    request.current?.controller.abort();
    request.current = null;
    setBusy(false);
    setError("");
    setRangeError("");
    setDenied(false);
    setNotice("");
    setRetry(null);
  }, [seasonId, basis, canDownload]);
  useEffect(() => {
    if (!ready) {
      request.current?.controller.abort();
      request.current = null;
      setBusy(false);
    }
  }, [ready]);
  const count = monthsBetween(from, to);
  const validation = !options.length
    ? "No saved CWL months available."
    : count < 1
      ? "To must be on or after From."
      : count > 12
        ? "Select no more than 12 calendar months."
        : "";
  const download = async (kind: "season" | "range") => {
    if (
      !canDownload ||
      !ready ||
      !seasonId ||
      busy ||
      request.current ||
      (kind === "range" && (!open || validation))
    )
      return;
    const controller = new AbortController();
    request.current = { controller, kind };
    setBusy(true);
    setError("");
    setRangeError("");
    setDenied(false);
    setNotice("");
    setRetry(null);
    const season = seasons.find((row) => String(row.id) === seasonId);
    const url =
      kind === "season"
        ? `/api/cwl/seasons/${encodeURIComponent(seasonId)}/export.xlsx?${new URLSearchParams({ basis })}`
        : `/api/cwl/exports/range.xlsx?${new URLSearchParams({ from, to })}`;
    try {
      const response = await fetchReadWithRetry(url, {
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        if (controller.signal.aborted) return;
        throw new ApiError(body?.error || "Download failed.", response.status);
      }
      if (!response.headers.get("content-type")?.includes(MIME))
        throw new Error("The server did not return an Excel workbook.");
      const file = await response.blob();
      if (controller.signal.aborted) return;
      const object = URL.createObjectURL(file),
        link = document.createElement("a");
      link.href = object;
      const header = response.headers
        .get("content-disposition")
        ?.match(/filename\*=UTF-8''([^;]+)/i);
      let name =
        kind === "season"
          ? `CWL ${season ? seasonMonthLabel(season) : "season"}.xlsx`
          : rangeName(from, to);
      if (header) {
        try {
          name = decodeURIComponent(header[1]);
        } catch {
          /* Keep the explicit safe fallback. */
        }
      }
      link.download = name.replace(/[\\/\r\n\x00-\x1f]/g, " ");
      document.body.append(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(object), 1000);
      setNotice("Excel download started. Check your browser downloads.");
    } catch (cause) {
      if (!controller.signal.aborted && mounted.current) {
        const forbidden =
          cause instanceof ApiError && [401, 403].includes(cause.status);
        setDenied(forbidden);
        const message = forbidden
          ? "You do not have access to this download."
          : cause instanceof ApiError && [400, 404, 409].includes(cause.status)
            ? cause.message
            : "Download failed.";
        if (kind === "range") setRangeError(message);
        else setError(message);
        setRetry(forbidden ? null : kind);
        if (forbidden) {
          onDenied();
          window.dispatchEvent(new Event("dashboard-access-changed"));
        }
      }
    } finally {
      if (request.current?.controller === controller) request.current = null;
      if (mounted.current && !controller.signal.aborted) setBusy(false);
    }
  };
  if (!canDownload) return null;
  return (
    <section className="export-downloads" aria-label="Excel downloads">
      <button
        className="primary"
        type="button"
        disabled={!ready || busy}
        onClick={() => void download("season")}
      >
        {busy && request.current?.kind === "season"
          ? "Preparing Excel…"
          : "Download season (Excel)"}
      </button>
      {error && (
        <p role="alert">
          {error}
          {retry === "season" && !denied && (
            <button
              type="button"
              disabled={busy}
              onClick={() => void download("season")}
            >
              Retry download
            </button>
          )}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      <details
        className="export-range"
        onToggle={(event) => {
          const next = event.currentTarget.open;
          setOpen(next);
          if (!next && request.current?.kind === "range") {
            request.current.controller.abort();
            request.current = null;
            setBusy(false);
            setRetry(null);
          }
        }}
      >
        <summary>Download a range…</summary>
        {open && (
          <div className="export-range-fields">
            <label>
              From
              <select
                name="export-from"
                value={from}
                disabled={busy}
                onChange={(e) => {
                  setFrom(e.target.value);
                  setRangeError("");
                  setRetry(null);
                }}
              >
                {options.map((month) => (
                  <option key={month} value={month}>
                    {exportMonthLabel(month)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              To
              <select
                name="export-to"
                value={to}
                disabled={busy}
                onChange={(e) => {
                  setTo(e.target.value);
                  setRangeError("");
                  setRetry(null);
                }}
              >
                {options.map((month) => (
                  <option key={month} value={month}>
                    {exportMonthLabel(month)}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              disabled={!ready || busy || Boolean(validation)}
              onClick={() => void download("range")}
            >
              {busy && request.current?.kind === "range"
                ? "Preparing Excel…"
                : "Download range"}
            </button>
            {validation && <p className="export-range-error">{validation}</p>}
            {rangeError && (
              <p className="export-range-error" role="alert">
                {rangeError}
                {retry === "range" && !denied && (
                  <button
                    type="button"
                    disabled={busy}
                    onClick={() => void download("range")}
                  >
                    Retry range
                  </button>
                )}
              </p>
            )}
          </div>
        )}
      </details>
    </section>
  );
}
