import { useEffect, useMemo, useState } from 'react'
import { ApiError } from '../api'
import { clearSnapshots } from '../snapshotCache'
import { fetchReadWithRetry } from '../readRetry'
import type { War } from './useClanActivity'

type Member = {tag: string; name: string; map_position: number | null; town_hall: number | null; attacks_used: number | null; attacks_total: number | null; linked: boolean | null}
type Attack = {side: 'clan' | 'opponent'; attacker_tag: string | null; attacker_name: string | null; defender_tag: string | null; defender_name: string | null; stars: number | null; destruction: number | null; order: number | null; duration: number | null; linked: boolean | null}
export type WarDetail = {checked_at: string; scope: 'mine' | 'family'; kind: 'regular' | 'cwl'; clan_tag: string; war_id: string; state: string; clan: {tag: string; name: string} | null; opponent: {tag: string; name: string} | null; team_size: number | null; attacks_per_member: number | null; starts_at: number | null; ends_at: number | null; lineup: {clan: Member[]; opponent: Member[]}; attacks: Attack[]; attacks_complete: boolean; lineup_complete: boolean; warnings?: string[]}
const PAGE_SIZE = 20
const MAX_ATTACKS = 500
function errorText(cause: unknown) { return cause instanceof Error ? cause.message : 'War details could not be loaded.' }
function nullableNumber(value: unknown) { return value == null || (typeof value === 'number' && Number.isFinite(value)) }
function validMember(value: unknown): value is Member {
  if (!value || typeof value !== 'object') return false
  const member = value as Partial<Member>
  return typeof member.tag === 'string' && typeof member.name === 'string'
    && nullableNumber(member.map_position) && nullableNumber(member.town_hall)
    && nullableNumber(member.attacks_used) && nullableNumber(member.attacks_total)
    && (member.linked == null || typeof member.linked === 'boolean')
}
function validAttack(value: unknown): value is Attack {
  if (!value || typeof value !== 'object') return false
  const attack = value as Partial<Attack>
  return (attack.side === 'clan' || attack.side === 'opponent')
    && (attack.attacker_tag == null || typeof attack.attacker_tag === 'string')
    && (attack.attacker_name == null || typeof attack.attacker_name === 'string')
    && (attack.defender_tag == null || typeof attack.defender_tag === 'string')
    && (attack.defender_name == null || typeof attack.defender_name === 'string')
    && nullableNumber(attack.stars) && nullableNumber(attack.destruction)
    && nullableNumber(attack.order) && nullableNumber(attack.duration)
    && (attack.linked == null || typeof attack.linked === 'boolean')
}
function validDetail(value: unknown): value is WarDetail {
  if (!value || typeof value !== 'object') return false
  const item = value as Partial<WarDetail>
  return typeof item.checked_at === 'string' && (item.scope === 'mine' || item.scope === 'family')
    && (item.kind === 'regular' || item.kind === 'cwl') && typeof item.clan_tag === 'string' && typeof item.war_id === 'string'
    && !!item.lineup && Array.isArray(item.lineup.clan) && item.lineup.clan.every(validMember)
    && Array.isArray(item.lineup.opponent) && item.lineup.opponent.every(validMember)
    && Array.isArray(item.attacks) && item.attacks.every(validAttack)
    && typeof item.attacks_complete === 'boolean' && typeof item.lineup_complete === 'boolean'
    && (item.warnings == null || (Array.isArray(item.warnings) && item.warnings.every(warning => typeof warning === 'string')))
    && (item.clan == null || (typeof item.clan.tag === 'string' && typeof item.clan.name === 'string'))
    && (item.opponent == null || (typeof item.opponent.tag === 'string' && typeof item.opponent.name === 'string'))
}
export async function readWarDetail({clanTag, type, scope, warId, signal, onAccessDenied}: {
  clanTag: string; type: 'regular' | 'cwl'; scope: 'mine' | 'family'; warId: string; signal: AbortSignal; onAccessDenied: () => void
}, read: typeof fetchReadWithRetry = fetchReadWithRetry): Promise<WarDetail> {
  const params = new URLSearchParams({scope, clan_tag: clanTag, kind: type, war_id: warId})
  const response = await read(`/api/cwl/war-detail?${params}`, {credentials: 'same-origin', signal})
  const body = await response.json().catch(() => null)
  if (!response.ok) {
    if (response.status === 401 || response.status === 403) onAccessDenied()
    const message = typeof body?.error === 'string' ? body.error : response.status === 409 ? 'This war changed or is no longer available. Refresh the war list to check again.' : response.status === 503 ? 'Game data is temporarily unavailable. Try again shortly.' : `War details could not be loaded (${response.status}).`
    throw new ApiError(message, response.status)
  }
  if (!validDetail(body)) throw new Error('War details were incomplete or malformed. Try again.')
  if (body.clan_tag !== clanTag || body.kind !== type || body.scope !== scope || body.war_id !== warId) {
    throw new ApiError('This war changed or is no longer available. Refresh the war list to check again.', 409)
  }
  const capped = body.attacks.length > MAX_ATTACKS
  return {...body, attacks: body.attacks.slice(0, MAX_ATTACKS), attacks_complete: body.attacks_complete && !capped}
}
function memberSummary(member: Member) {
  const used = member.attacks_used == null ? 'Attacks unknown' : `${member.attacks_used}/${member.attacks_total ?? '—'} attacks used`
  return <li className="war-detail-member" key={member.tag}>
    <span className="war-detail-member-title">{member.map_position == null ? '' : <b>#{member.map_position} </b>}{member.name} <small>{member.tag}</small>{member.linked === true && <span className="war-detail-linked">Your account</span>}</span>
    <span className="war-detail-member-meta">{member.town_hall == null ? 'TH unknown' : `TH ${member.town_hall}`} · {used}</span>
  </li>
}
export default function WarDetailPanel({clanTag, type, scope, war, onAccessDenied, onRefreshOverview}: {clanTag: string; type: 'regular' | 'cwl'; scope: 'mine' | 'family'; war: War; onAccessDenied: () => void; onRefreshOverview: () => void}) {
  const [data, setData] = useState<WarDetail | null>(null)
  const [error, setError] = useState('')
  const [errorStatus, setErrorStatus] = useState<number | null>(null)
  const [busy, setBusy] = useState(false)
  const [revision, setRevision] = useState(0)
  const [view, setView] = useState<'lineup' | 'attacks'>('lineup')
  const [side, setSide] = useState<'clan' | 'opponent'>('clan')
  const [page, setPage] = useState(0)
  const warId = war.war_id || ''
  useEffect(() => {
    const controller = new AbortController()
    let active = true
    async function load() {
      setBusy(true); setError(''); setErrorStatus(null); setData(null); setPage(0); setView('lineup')
      try {
        const detail = await readWarDetail({clanTag, type, scope, warId, signal: controller.signal, onAccessDenied: () => {
          clearSnapshots()
          window.dispatchEvent(new Event('dashboard-access-changed'))
          onAccessDenied()
        }})
        if (active) setData(detail)
      } catch (cause) {
        if (active && !controller.signal.aborted) {
          if (cause instanceof ApiError) setErrorStatus(cause.status)
          setError(errorText(cause))
        }
      } finally { if (active) setBusy(false) }
    }
    void load()
    return () => { active = false; controller.abort() }
  }, [clanTag, type, scope, warId, revision, onAccessDenied])
  const members = data?.lineup[side] || []
  const attacks = data?.attacks || []
  const pageCount = Math.max(1, Math.ceil((view === 'lineup' ? members.length : attacks.length) / PAGE_SIZE))
  const visibleMembers = useMemo(() => members.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), [members, page])
  const visibleAttacks = useMemo(() => attacks.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE), [attacks, page])
  return <section className="war-detail-panel" aria-label="War lineups and attacks">
    {busy && <p role="status">Loading lineups and attacks…</p>}
    {error && <div className="war-detail-error" role="alert"><p>{error}</p>{errorStatus !== 409 && <button type="button" onClick={() => setRevision(value => value + 1)}>Retry details</button>}{errorStatus === 409 && <button type="button" onClick={onRefreshOverview}>Refresh war list</button>}</div>}
    {data && <>
      <div className="war-detail-freshness">Checked {Number.isFinite(Date.parse(data.checked_at)) ? new Date(data.checked_at).toLocaleString() : data.checked_at}</div>
      {data.warnings?.length ? <ul className="war-detail-partial" aria-label="War detail notes">{data.warnings.map((warning, index) => <li key={`${index}:${warning}`}>{warning}</li>)}</ul> : null}
      <div className="war-detail-view" role="group" aria-label="War detail view"><button type="button" aria-pressed={view === 'lineup'} onClick={() => {setView('lineup'); setPage(0)}}>Lineup</button><button type="button" aria-pressed={view === 'attacks'} onClick={() => {setView('attacks'); setPage(0)}}>Attack log</button></div>
      {view === 'lineup' ? <>
        {!data.lineup_complete && <p className="war-detail-partial" role="status">Lineup data is partial; some bases may be missing.</p>}
        <div className="war-detail-side" role="group" aria-label="Lineup side"><button type="button" aria-pressed={side === 'clan'} onClick={() => {setSide('clan'); setPage(0)}}>{data.clan?.name || 'Your clan'}</button><button type="button" aria-pressed={side === 'opponent'} onClick={() => {setSide('opponent'); setPage(0)}}>{data.opponent?.name || 'Opponent'}</button></div>
        <h3>{side === 'clan' ? data.clan?.name || 'Your clan' : data.opponent?.name || 'Opponent'} lineup <small>{members.length}{data.team_size == null ? '' : `/${data.team_size}`}</small></h3>
        {members.length ? <ol className="war-detail-lineup-list">{visibleMembers.map(memberSummary)}</ol> : <p>Lineup unavailable.</p>}
      </> : <section className="war-detail-attacks" aria-label="Attack log">
        <header><h3>Attack log <small>{attacks.length}{data.attacks_complete ? '' : '+'}</small></h3><span>{data.attacks_per_member == null ? 'Attack limit unknown' : `${data.attacks_per_member} ${data.attacks_per_member === 1 ? 'attack' : 'attacks'} per member`}</span></header>
        {!data.attacks_complete && <p className="war-detail-partial" role="status">Attack log is partial or capped; the total may be higher.</p>}
        {!attacks.length ? <p>{data.attacks_complete ? 'No attacks are available in this war log.' : 'No complete attack entries are available.'}</p> : <ol className="war-detail-attack-list">{visibleAttacks.map((attack, index) => <li key={`${page * PAGE_SIZE + index}:${attack.side}`}>
          <div><span className="war-detail-attack-side">{attack.side === 'clan' ? data.clan?.name || 'Your clan' : data.opponent?.name || 'Opponent'}</span> <b>{attack.order == null ? `Attack ${page * PAGE_SIZE + index + 1}` : `#${attack.order}`}</b> {attack.attacker_name || 'Attacker unknown'} <small>{attack.attacker_tag || 'Tag unavailable'}</small>{attack.linked === true && <span className="war-detail-linked">Your account</span>}</div>
          <div><span>→ {attack.defender_name || 'Target unknown'} <small>{attack.defender_tag || 'Tag unavailable'}</small></span><strong>{attack.stars == null ? 'Stars unknown' : `${attack.stars} ★`} · {attack.destruction == null ? 'Destruction unknown' : `${attack.destruction}%`}</strong></div>
        </li>)}</ol>}
      </section>}
      {pageCount > 1 && <nav className="war-detail-pages" aria-label={view === 'lineup' ? 'Lineup pages' : 'Attack log pages'}><button type="button" disabled={page === 0} onClick={() => setPage(value => value - 1)}>Previous</button><span>Page {page + 1} of {pageCount}</span><button type="button" disabled={page + 1 >= pageCount} onClick={() => setPage(value => value + 1)}>Next</button></nav>}
    </>}
  </section>
}
