import { useEffect, useRef, useState } from 'react';
import { api, ApiError, type Season } from './api';
import { syncStatusLabel } from './participation';
import './ExportWorkspace.css';
import { bonusSelectionReason, bonusSelectionStatus, matchesExportSearch, rosterResultSummary } from './exportPreview';

type Kind = 'accounts' | 'participation' | 'participation-history' | 'bonus-history';
type Basis = 'current' | 'published';
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
type Props = { seasonId: string; seasons: Season[]; onSeasonChange: (id: string) => void };

const choices: { kind: Kind; label: string; description: string }[] = [
  { kind: 'accounts', label: 'Accounts, weights & results', description: 'Roster accounts, weights, recorded results, and saved bonus status.' },
  { kind: 'participation', label: 'Current signup results', description: 'Current signups and working assignments; removed accounts are excluded.' },
  { kind: 'participation-history', label: 'Saved participation history', description: 'Recorded results and staff notes, including removed signups.' },
  { kind: 'bonus-history', label: 'Bonus selection history', description: 'Saved and voided dashboard selections; these are not confirmed game awards.' },
];
const rowLimit = 20;
const stringValue = (value: unknown) => value === null || value === undefined || value === '' ? '—' : String(value);
const cell = (row: PreviewRow, key: string) => stringValue(row[key]);
const displayField = (row: PreviewRow, key: string) => {
  if (key === 'pool') return row.pool === 'main' ? 'Main CWL' : row.pool === 'lazy' ? 'Lazy CWL' : cell(row, key);
  if (key === 'source_status') return syncStatusLabel(row.source_status as string | null | undefined);
  if (key === 'confirmed_at' && row.confirmed_at) return dateText(String(row.confirmed_at));
  return cell(row, key);
};
const dateText = (value: string | null) => value ? new Date(value).toLocaleString() : 'Never';
const errorText = (cause: unknown) => cause instanceof Error ? cause.message : 'Could not load the export preview.';

function previewFields(kind: Kind): { key: string; label: string }[] {
  switch (kind) {
    case 'accounts': return [
      { key: 'player_name', label: 'Player' }, { key: 'pool', label: 'CWL' },
      { key: 'assigned_clan_name', label: 'Hosting clan' }, { key: 'effective_weight', label: 'Weight' },
      { key: 'result_summary', label: 'Results for this roster' },
    ];
    case 'participation': return [
      { key: 'player_name', label: 'Player' }, { key: 'pool', label: 'CWL' },
      { key: 'assigned_clan_name', label: 'Hosting clan' }, { key: 'result_summary', label: 'Results for this roster' },
      { key: 'source_status', label: 'Source' },
    ];
    case 'participation-history': return [
      { key: 'player_name', label: 'Player' }, { key: 'pool', label: 'CWL' },
      { key: 'assigned_clan_name', label: 'Hosting clan' }, { key: 'attacks', label: 'Attacks' },
      { key: 'stars', label: 'Stars' }, { key: 'source_status', label: 'Source' },
    ];
    case 'bonus-history': return [
      { key: 'player_name', label: 'Player' }, { key: 'clan_name', label: 'Hosting clan' },
      { key: 'cycle', label: 'CWL month' }, { key: 'selection_status', label: 'Status' },
      { key: 'confirmed_at', label: 'Selected on' }, { key: 'selection_reason', label: 'Reason' },
    ];
  }
}

export default function ExportWorkspace({ seasonId, seasons, onSeasonChange }: Props) {
  const [kind, setKind] = useState<Kind>('accounts');
  const [basis, setBasis] = useState<Basis>('current');
  const [preview, setPreview] = useState<ExportPreview | null>(null);
  const [previewFor, setPreviewFor] = useState('');
  const [publicationAvailable, setPublicationAvailable] = useState<boolean | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [previewError, setPreviewError] = useState('');
  const [downloadBusy, setDownloadBusy] = useState(false);
  const [downloadError, setDownloadError] = useState('');
  const [notice, setNotice] = useState('');
  const [search, setSearch] = useState('');
  const [page, setPage] = useState(0);
  const [attempt, setAttempt] = useState(0);
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
    setPublicationAvailable(null);
  }, [seasonId]);
  useEffect(() => {
    downloadController.current?.abort();
    setDownloadBusy(false);
    setDownloadError('');
    setNotice('');
    setSearch('');
    setPage(0);
  }, [seasonId, kind, basis]);
  useEffect(() => {
    const request = ++previewRequest.current;
    setPreview(null);
    setPreviewFor('');
    setPreviewError('');
    if (!seasonId) { setPreviewLoading(false); return; }
    setPreviewLoading(true);
    const params = new URLSearchParams({ kind, basis: kind === 'accounts' ? basis : 'current' });
    api<ExportPreview>(`/seasons/${encodeURIComponent(seasonId)}/export-preview?${params}`)
      .then(result => {
        if (request !== previewRequest.current) return;
        setPreview(result);
        setPublicationAvailable(result.summary.published_available);
        setPreviewFor(`${seasonId}|${kind}|${kind === 'accounts' ? basis : 'current'}`);
      })
      .catch(cause => {
        if (request !== previewRequest.current) return;
        setPreviewError(errorText(cause));
        if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
          setPreview(null);
          setPublicationAvailable(null);
        }
      })
      .finally(() => { if (request === previewRequest.current) setPreviewLoading(false); });
    return () => { previewRequest.current += 1; };
  }, [seasonId, kind, basis, attempt]);

  const changeSeason = (id: string) => {
    downloadController.current?.abort();
    setPreview(null);
    setPublicationAvailable(null);
    setBasis('current');
    onSeasonChange(id);
  };
  const changeKind = (next: Kind) => {
    downloadController.current?.abort();
    setPreview(null);
    setKind(next);
    setBasis('current');
  };
  const download = async () => {
    if (!seasonId || !displayedPreview || previewLoading || downloadBusy) return;
    const controller = new AbortController();
    downloadController.current = controller;
    setDownloadBusy(true);
    setDownloadError('');
    setNotice('');
    const chosenBasis = kind === 'accounts' ? basis : 'current';
    try {
      const params = new URLSearchParams({ kind, basis: chosenBasis });
      const response = await fetch(`/api/cwl/seasons/${encodeURIComponent(seasonId)}/export.csv?${params}`, {
        credentials: 'same-origin', signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      if (!response.ok) {
        const body = await response.json().catch(() => null);
        if (controller.signal.aborted) return;
        if (response.status === 401 || response.status === 403) {
          setPreview(null);
          window.dispatchEvent(new Event('dashboard-access-changed'));
        }
        throw new Error(body?.error || `Could not download this export (${response.status}). Sign in again or retry.`);
      }
      if (!response.headers.get('content-type')?.includes('text/csv')) throw new Error('The server did not return a CSV file. Refresh the page and try again.');
      const file = await response.blob();
      if (controller.signal.aborted) return;
      const url = URL.createObjectURL(file);
      const link = document.createElement('a');
      link.href = url;
      link.download = `cwl-season-${seasonId}-${kind}-${chosenBasis}.csv`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice('CSV download started. Check your browser downloads.');
    } catch (cause) {
      if (!controller.signal.aborted) setDownloadError(cause instanceof Error ? cause.message : 'Export failed. Please try again.');
    } finally {
      if (downloadController.current === controller) downloadController.current = null;
      if (mounted.current && !controller.signal.aborted) setDownloadBusy(false);
    }
  };

  const context = `${seasonId}|${kind}|${kind === 'accounts' ? basis : 'current'}`;
  const displayedPreview = previewFor === context ? preview : null;
  const fields = previewFields(kind);
  const query = search.trim().toLocaleLowerCase();
  const rows = (displayedPreview?.rows || []).filter(row => matchesExportSearch(row, query, kind));
  const lastPage = Math.max(0, Math.ceil(rows.length / rowLimit) - 1);
  const currentPage = Math.min(page, lastPage);
  const shown = rows.slice(currentPage * rowLimit, (currentPage + 1) * rowLimit);
  const publishedAvailable = publicationAvailable === true;
  const selectedSeason = seasons.find(season => String(season.id) === seasonId);

  return <div className="export-workspace">
    <div className="page-head export-page-head">
      <div><p className="eyebrow">CWL · Records</p><h1>Exports &amp; history</h1></div>
      <label className="season-choice">Season
        <select disabled={downloadBusy} value={seasonId} onChange={event => changeSeason(event.target.value)}>
          <option value="">Select a season</option>
          {seasons.map(season => <option value={String(season.id)} key={season.id}>{season.label}{season.status === 'archived' ? ' · Archived' : ''}</option>)}
        </select>
      </label>
    </div>
    {!seasonId && <p className="export-empty">Select a season to review and export its records.</p>}
    {seasonId && <>
      <div className="export-season-status" role="status">
        <span>{selectedSeason?.status === 'archived' ? 'Archived season' : 'Working season'}</span>
        <span>{displayedPreview ? displayedPreview.summary.published_version ? `Published roster v${displayedPreview.summary.published_version} · ${dateText(displayedPreview.summary.published_at)}` : 'No roster published yet' : previewLoading ? 'Checking publication…' : 'Publication status unavailable'}</span>
        {displayedPreview?.summary.cwl_month && <span>CWL month {displayedPreview.summary.cwl_month}</span>}
      </div>
      <div className="export-controls">
        <label>Records
          <select value={kind} disabled={downloadBusy} onChange={event => changeKind(event.target.value as Kind)}>
            {choices.map(choice => <option key={choice.kind} value={choice.kind}>{choice.label}</option>)}
          </select>
        </label>
        {kind === 'accounts' && <label>Roster version
          <select value={basis} disabled={downloadBusy || previewLoading} onChange={event => { setPreview(null); setBasis(event.target.value as Basis); setPage(0); }}>
            <option value="current">Saved working placements</option>
            <option value="published" disabled={!publishedAvailable}>Latest published roster{publishedAvailable ? ` · v${displayedPreview?.summary.published_version}` : ' · unavailable'}</option>
          </select>
        </label>}
        <p>{choices.find(choice => choice.kind === kind)?.description}</p>
      </div>
      {previewLoading && <p role="status">Loading export preview…</p>}
      {previewError && <div className="notice error" role="alert">{previewError}<button type="button" onClick={() => setAttempt(value => value + 1)}>Retry</button></div>}
      {downloadError && <div className="notice error" role="alert">{downloadError}</div>}
      {notice && <div className="notice success" role="status">{notice}</div>}
      {displayedPreview && !previewLoading && <>
        <div className="export-ready">
          <div><strong>{displayedPreview.counts.rows} {displayedPreview.counts.rows === 1 ? 'row' : 'rows'} ready</strong><span>CSV includes all saved rows, regardless of search.</span></div>
          <button type="button" className="primary" disabled={downloadBusy} onClick={() => void download()}>{downloadBusy ? 'Preparing CSV…' : 'Download CSV'}</button>
        </div>
        {kind === 'accounts' && <p className="export-basis-note">{basis === 'published' ? 'Published roster placements and weights are frozen; separately recorded results may update.' : 'Saved working placements use the latest weights and results, including in archived seasons.'}</p>}
        {rows.some(row => kind === 'accounts' ? row.participation_matches_roster === false : kind === 'participation' && row.matches_roster === false) && <p className="export-mismatch-note">Some results belong to another assignment, so they are blank in this roster export. Find the original results in Saved participation history.</p>}
        <div className="export-list-head"><strong>Preview</strong><span>{rows.length} matching · {displayedPreview.counts.rows} total</span></div>
        <label className="export-search">Find a record
          <input type="search" value={search} onChange={event => { setSearch(event.target.value); setPage(0); }} placeholder="Player, tag, clan or reason" />
        </label>
        {!rows.length ? <p className="export-empty">{query ? 'No records match this search.' : 'No saved records for this export.'}</p> : <>
          <div className="export-records" role="list">
            {shown.map((row, index) => <div className="export-record" role="listitem" key={`${kind}:${currentPage}:${index}:${cell(row, 'tag')}`}>
              <div className="export-record-name"><strong>{cell(row, 'player_name')}</strong><small>{cell(row, 'tag')}</small></div>
              {fields.filter(field => field.key !== 'player_name').map(field => <div key={field.key} className="export-record-field"><small>{field.label}</small><span>{field.key === 'result_summary' ? rosterResultSummary(row, kind === 'accounts' ? 'participation_' : '') : kind === 'bonus-history' && field.key === 'selection_status' ? bonusSelectionStatus(row) : kind === 'bonus-history' && field.key === 'selection_reason' ? bonusSelectionReason(row) : displayField(row, field.key)}</span></div>)}
              {kind === 'participation-history' && Boolean(row.notes || row.updated_at) && <details className="export-record-details"><summary>Saved details</summary>
                {Boolean(row.updated_at) && <p>Last saved {dateText(String(row.updated_at))}</p>}
                {Boolean(row.notes) && <p>{String(row.notes)}</p>}
              </details>}
            </div>)}
          </div>
          {lastPage > 0 && <nav className="roster-pagination" aria-label="Export preview pages">
            <button type="button" disabled={currentPage === 0} onClick={() => setPage(currentPage - 1)}>Previous</button>
            <span>Page {currentPage + 1} of {lastPage + 1}</span>
            <button type="button" disabled={currentPage === lastPage} onClick={() => setPage(currentPage + 1)}>Next</button>
          </nav>}
        </>}
        <details className="export-about"><summary>CSV format &amp; data</summary><p>Blank results remain blank. Weights use full numbers; Discord IDs remain complete. Names and notes are protected from running as spreadsheet formulas. The file reflects saved records at download time.</p></details>
      </>}
    </>}
  </div>;
}
