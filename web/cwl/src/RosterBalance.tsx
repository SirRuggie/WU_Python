import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { api } from './api';
import type { AutoPreview, RosterSnapshot } from './roster';
import './RosterPlayerDialog.css';

type Props = { roster: RosterSnapshot; seasonId: string; tags: string[];
  onClose: () => void; onSaved: () => Promise<void>; onBusy: (busy: boolean) => void };
const reasons: Record<string, string> = { locked: 'Locked placement', missing_weight: 'Missing weight',
  source_unavailable: 'Weight source unavailable', full: 'No room in selected clans', no_eligible_rule: 'No selected clan matches the pool and weight rules' };
export default function RosterBalance({ roster, seasonId, tags, onClose, onSaved, onBusy }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const pending = useRef(false);
  const [hosts, setHosts] = useState<string[]>([]);
  const [includeLocked, setIncludeLocked] = useState(false);
  const [preview, setPreview] = useState<AutoPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const pools = new Set(roster.accounts.filter(a => tags.includes(a.tag)).map(a => a.pool));
  const clans = roster.clans.filter(c => !c.archived && c.pool && pools.has(c.pool));
  useEffect(() => {
    const trigger = document.activeElement as HTMLElement | null;
    dialog.current?.showModal();
    return () => { dialog.current?.close(); trigger?.focus(); };
  }, []);
  const run = async (apply: boolean) => {
    if (pending.current) return;
    pending.current = true; setBusy(true); onBusy(true); setError('');
    try {
      const body = { mode: 'balance', revision: preview?.revision ?? roster.revision,
        tags, clan_tags: hosts, include_locked: includeLocked };
      if (apply && preview) {
        await api(`/seasons/${encodeURIComponent(seasonId)}/roster/auto-apply`, 'POST', { ...body, placements: preview.placements });
        await onSaved(); onClose();
      } else {
        setPreview(await api<AutoPreview>(`/seasons/${encodeURIComponent(seasonId)}/roster/auto-preview`, 'POST', body));
      }
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not balance accounts. Try again.'); }
    finally { pending.current = false; setBusy(false); onBusy(false); }
  };
  const clanName = (tag: string | null) => roster.clans.find(c => c.tag === tag)?.name || tag || 'Unassigned';
  const projected = roster.accounts.map(a => ({ ...a, assigned_clan_tag: preview?.placements.find(p => p.tag === a.tag)?.assigned_clan_tag ?? a.assigned_clan_tag }));
  const affected = new Set([...hosts, ...roster.accounts.filter(a => preview?.placements.some(p => p.tag === a.tag)).map(a => a.assigned_clan_tag)]);
  return createPortal(<dialog aria-labelledby="balance-heading" className="roster-player-dialog" ref={dialog} onCancel={e => { e.preventDefault(); if (!pending.current) onClose(); }}>
    <div className="roster-balance">
      <div className="row"><h2 id="balance-heading">Balance across clans</h2><button disabled={busy} onClick={onClose}>Close ×</button></div>
      <p>{tags.length} accounts selected. Signups stay unchanged.</p>
      {error && <p role="alert" className="notice error">{error}</p>}
      {!preview ? <>
        <p><strong>1. Choose clans</strong> → 2. Review moves</p>
        <fieldset disabled={busy}><legend>Which clans should share these accounts?</legend>
          <small>Tick two or more clans. You do not need to unassign accounts first.</small>
          {clans.map(c => <label className={`roster-balance-choice${hosts.includes(c.tag) ? " is-selected" : ""}`} key={c.tag}><input type="checkbox" checked={hosts.includes(c.tag)}
            disabled={!c.capacity || ![15, 30].includes(c.capacity)}
            onChange={e => setHosts(e.target.checked ? [...hosts, c.tag] : hosts.filter(t => t !== c.tag))} />
            <span>{c.name}<small>{c.pool === 'lazy' ? 'Lazy' : 'Main'} · {c.assigned_count}/{c.capacity || 'Not configured'} accounts{!c.capacity ? ' · Set capacity in Clan settings first' : ''}</small></span></label>)}
          {!clans.length && <p>No matching hosting clans. Set up clan rules first.</p>}
        </fieldset>
        <p role="status">{hosts.length} clans selected{hosts.length < 2 ? " · Choose at least 2" : ""}</p>
        <label className="roster-balance-choice"><input type="checkbox" checked={includeLocked} disabled={busy} onChange={e => setIncludeLocked(e.target.checked)} />Include locked placements</label>
        <small>Spreads similar weights evenly, then favors lower total weight. Clan rules and capacity still apply. Moved locked accounts stay locked.</small>
        <button className="primary" disabled={busy || hosts.length < 2 || tags.length > 50} onClick={() => void run(false)}>{busy ? 'Preparing…' : hosts.length < 2 ? 'Choose at least 2 clans' : `Preview balance across ${hosts.length} clans`}</button>
      </> : <>
        <p>1. Choose clans → <strong>2. Review moves</strong></p>
        <p>{preview.placements.length} moves · {preview.unassigned.length} skipped</p>
        <div className="roster-balance-totals">{roster.clans.filter(c => affected.has(c.tag)).map(c => {
          const before = roster.accounts.filter(a => a.assigned_clan_tag === c.tag);
          const after = projected.filter(a => a.assigned_clan_tag === c.tag);
          const total = after.reduce((sum, a) => sum + (a.effective_weight || 0), 0);
          const missing = after.filter(a => a.effective_weight === null).length;
          return <div key={c.tag}><strong>{c.name}</strong><span>{before.length} → {after.length}/{c.effective_capacity} accounts</span><span>Total weight {total.toLocaleString('en-US')}{missing ? ` · ${missing} missing` : ''}</span></div>;
        })}</div>
        <details><summary>Review account moves</summary>{preview.placements.map(p => { const a = roster.accounts.find(a => a.tag === p.tag); return <p key={p.tag}><strong>{a?.player_name || p.tag}</strong><br />{clanName(a?.assigned_clan_tag || null)} → {clanName(p.assigned_clan_tag)}</p>; })}</details>
        {!!preview.unassigned.length && <details open><summary>Accounts staying in place</summary>{preview.unassigned.map(p => <p key={p.tag}>{roster.accounts.find(a => a.tag === p.tag)?.player_name || p.tag}: {reasons[p.reason] || p.reason}</p>)}</details>}
        <small>Changes affect the working roster. Publish separately when ready.</small>
        <div className="row"><button disabled={busy} onClick={() => { setPreview(null); setError(''); }}>Back</button><button className="primary" disabled={busy || !preview.placements.length} onClick={() => void run(true)}>{busy ? 'Applying…' : 'Apply balance'}</button></div>
      </>}
    </div>
  </dialog>, document.body);
}
