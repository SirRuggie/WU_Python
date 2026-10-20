// Local visual fixture. This page is separate from the signed-in dashboard.
import React from 'react'
import { createRoot } from 'react-dom/client'
import StrikesWorkspace from './StrikesWorkspace'
import ReplacementWorkspace from './ReplacementWorkspace'
import './style.css'

const now = '2026-10-20T12:00:00Z'
const entries = [
  { id: '1', player_tag: '#P22ABC', player_name: 'CastleFox', discord_id: '123456789012345678', discord_name: 'Fox', current_clan_name: 'Warriors United FWA', war_clan_name: 'Warriors United FWA', opponent_name: 'Edrag Rush', war_key: 'war-fwa-edrag', war_end: now, kind: 'strike', source: 'war', status: 'active' },
  { id: '2', player_tag: '#Q99XYZ', player_name: 'BlueDragon', discord_id: '123456789012345679', discord_name: 'Dragon', current_clan_name: 'WU North', war_clan_name: 'Warriors United FWA', opponent_name: 'Edrag Rush', war_key: 'war-fwa-edrag', war_end: now, kind: 'miss', source: 'war', status: 'recorded' },
  { id: '3', player_tag: '#8LQQRT', player_name: 'LittleThunder', discord_id: '123456789012345678', discord_name: 'Fox', current_clan_name: 'WU North', war_clan_name: 'Warriors United FWA', war_end: '2026-09-03T12:00:00Z', kind: 'strike', source: 'manual', status: 'expired', reason: 'Missed war meeting' },
]
const wars = [{ war_key: 'war-fwa-edrag', clan_tag: '#FWA', clan_name: 'Warriors United FWA', opponent_tag: '#EDRAG', opponent_name: 'Edrag Rush', war_end: now, missed_accounts: 2, strikes: 1, one_missed: 1 }]
const candidates = [
  { player_tag: '#P22ABC', player_name: 'CastleFox', clan_tag: '#FWA', clan_name: 'Warriors United FWA', weight: 115000, active_strikes: 1, is_filler: true, is_manual: true, priority: 'replace_first', note: 'Temporary filler', weight_difference: 0, discord_name: 'Fox' },
  { player_tag: '#P44DEF', player_name: 'MiniWolf', clan_tag: '#FWA', clan_name: 'Warriors United FWA', weight: 114000, active_strikes: 3, is_filler: false, is_manual: false, priority: 'normal', weight_difference: 1000 },
  { player_tag: '#P55GHI', player_name: 'GreenOak', clan_tag: '#FWA2', clan_name: 'WU FWA Two', weight: 115000, active_strikes: 2, is_filler: false, is_manual: true, priority: 'high', note: 'Free a space soon', weight_difference: 0 },
]
const settings = { excluded_roles: [{ id: '769130325460254740', name: 'Strike exempt' }], roles: [{ id: '769130325460254740', name: 'Strike exempt' }, { id: '123456789012345600', name: 'Leave team' }], leaves: [{ discord_id: '123456789012345678', display_name: 'Fox', player_tags: ['#P22ABC', '#8LQQRT'], resume_date: '2026-11-01' }] }
const members = [{ id: '123456789012345678', name: 'Fox', accounts: [{ tag: '#P22ABC', name: 'CastleFox', current_clan_name: 'Warriors United FWA' }, { tag: '#8LQQRT', name: 'LittleThunder', current_clan_name: 'WU North' }] }]
const preview = { preview_id: 'fixture-preview', wars_scanned: 7, complete_wars: 6, incomplete_wars: 1, coverage: [{ clan_name: 'Warriors United FWA', wars: 4, earliest: '2026-09-22T12:00:00Z', latest: now }, { clan_name: 'WU North', wars: 3, earliest: '2026-10-01T12:00:00Z', latest: now }], entries: [{ key: 'war-1-a', player_tag: '#P22ABC', player_name: 'CastleFox', clan_name: 'Warriors United FWA', war_end: now, missed_attacks: 2, will_strike: true }, { key: 'war-2-b', player_tag: '#Q99XYZ', player_name: 'BlueDragon', clan_name: 'WU North', war_end: now, missed_attacks: 1, will_strike: false }] }

const fixtureJobs = new Map<string, { reads: number; result: unknown }>()
const realFetch = window.fetch.bind(window)
window.fetch = async (input, init) => {
  const url = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.origin)
  const path = url.pathname
  if (!path.startsWith('/api/cwl/strikes/')) return realFetch(input, init)
  const method = init?.method || 'GET'
  let data: unknown = { ok: true }
  if (path.endsWith('/strikes/accounts')) {
    const accounts = [
      { player_tag: '#P22ABC', player_name: 'CastleFox', discord_id: '123456789012345678', current_clan_tag: '#FWA', current_clan_name: 'Warriors United FWA', clan_is_current: true, active_strikes: 3, total_strikes: 4, last_strike_at: now },
      { player_tag: '#8LQQRT', player_name: 'LittleThunder', discord_id: '123456789012345678', current_clan_tag: '#NORTH', current_clan_name: 'WU North', clan_is_current: false, active_strikes: 0, total_strikes: 1, last_strike_at: '2026-09-03T12:00:00Z' },
    ]
    const query = (url.searchParams.get('query') || '').toLowerCase()
    const filtered = accounts.filter(item => (url.searchParams.get('status') === 'all' || item.active_strikes > 0) && (!query || `${item.player_name} ${item.player_tag} ${item.discord_id}`.toLowerCase().includes(query)))
    data = { accounts: filtered, total: filtered.length, clans: [{ tag: '#FWA', name: 'Warriors United FWA', is_fwa: true }, { tag: '#NORTH', name: 'WU North' }] }
  } else if (path.endsWith('/overview')) {
    const filtered = entries.filter(item => (!url.searchParams.get('war_key') || item.war_key === url.searchParams.get('war_key')) && (!url.searchParams.get('query')?.startsWith('#') || item.player_tag === url.searchParams.get('query')) && (url.searchParams.get('status') !== 'strikes' || item.kind === 'strike'))
    data = { entries: filtered, clans: [{ tag: '#FWA', name: 'Warriors United FWA', is_fwa: true }, { tag: '#NORTH', name: 'WU North' }], total: filtered.length }
  } else if (path.endsWith('/wars')) data = { wars: wars.filter(item => (!url.searchParams.get('clan') || item.clan_tag === url.searchParams.get('clan')) && (!url.searchParams.get('query') || `${item.clan_name} ${item.opponent_name}`.toLowerCase().includes(url.searchParams.get('query')!.toLowerCase()))) }
  else if (path.endsWith('/members')) data = { members: members.map(item => ({ ...item, accounts: [] })) }
  else if (path.includes('/members/') && path.endsWith('/accounts')) data = { member: members[0] }
  else if (path.endsWith('/settings')) data = settings
  else if (path.endsWith('/replacement-roster')) data = { accounts: (url.searchParams.get('clan') === '#FWA' ? [{ player_tag: '#P22ABC', player_name: 'CastleFox', is_manual: true }, { player_tag: '#P44DEF', player_name: 'MiniWolf', is_manual: false }, { player_tag: '#P88NEW', player_name: 'StoneBird', is_manual: false }] : [{ player_tag: '#P55GHI', player_name: 'GreenOak', is_manual: true }, { player_tag: '#P66JKL', player_name: 'RedRock', is_manual: false }]) }
  else if (path.endsWith('/replacements')) data = { candidates: candidates.filter(item => !url.searchParams.get('clan') || item.clan_tag === url.searchParams.get('clan')), clans: [{ tag: '#FWA', name: 'Warriors United FWA', is_fwa: true }, { tag: '#FWA2', name: 'WU FWA Two', is_fwa: true }, { tag: '#NORTH', name: 'WU North', is_fwa: false }] }
  else if (path.endsWith('/import/preview') || path.endsWith('/import/apply')) {
    const job_id = crypto.randomUUID()
    fixtureJobs.set(job_id, { reads: 0, result: path.endsWith('/preview') ? preview : { applied: 2, strikes: 1, skipped: 0 } })
    data = { job_id, status: 'running' }
  } else if (path.includes('/import/jobs/')) {
    const job_id = path.split('/').at(-1) || ''
    const job = fixtureJobs.get(job_id)
    if (job) { job.reads++; data = job.reads < 2 ? { job_id, status: 'running' } : { job_id, status: 'complete', result: job.result } }
    else data = { job_id, status: 'failed', error: 'Job unavailable' }
  }
  return new Response(JSON.stringify(data), { status: method === 'POST' ? 202 : 200, headers: { 'Content-Type': 'application/json' } })
}

const fixtureScope = new URLSearchParams(location.search).get('scope')
const fixturePermissions = fixtureScope === 'add' ? ['strikes_add'] : fixtureScope === 'remove' ? ['strikes_remove'] : fixtureScope === 'manage' ? ['strikes'] : ['strikes', 'strikes_add', 'strikes_remove']
createRoot(document.getElementById('root')!).render(<React.StrictMode><main style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 20px" }}>{new URLSearchParams(location.search).get('page') === 'replacements' ? <ReplacementWorkspace permissions={fixturePermissions} isOwner={false} /> : <StrikesWorkspace permissions={fixturePermissions} isOwner={false} userId="fixture" />}</main></React.StrictMode>)
