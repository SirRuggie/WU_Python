// Local visual fixture. This page is separate from the signed-in dashboard.
import React from 'react'
import { createRoot } from 'react-dom/client'
import StrikesWorkspace from './StrikesWorkspace'
import './style.css'

const now = '2026-10-20T12:00:00Z'
const entries = [
  { id: '1', player_tag: '#P22ABC', player_name: 'CastleFox', discord_id: '123456789012345678', discord_name: 'Fox', current_clan_name: 'Warriors United FWA', war_clan_name: 'Warriors United FWA', war_end: now, kind: 'strike', source: 'war', status: 'active' },
  { id: '2', player_tag: '#Q99XYZ', player_name: 'BlueDragon', discord_id: '123456789012345679', discord_name: 'Dragon', current_clan_name: 'WU North', war_clan_name: 'WU North', war_end: '2026-10-16T12:00:00Z', kind: 'miss', source: 'war', status: 'recorded' },
  { id: '3', player_tag: '#8LQQRT', player_name: 'LittleThunder', discord_id: '123456789012345678', discord_name: 'Fox', current_clan_name: 'WU North', war_clan_name: 'Warriors United FWA', war_end: '2026-09-03T12:00:00Z', kind: 'strike', source: 'manual', status: 'expired', reason: 'Missed war meeting' },
]
const candidates = [
  { player_tag: '#P22ABC', player_name: 'CastleFox', clan_tag: '#FWA', clan_name: 'Warriors United FWA', weight: 115000, active_strikes: 1, is_filler: true, weight_difference: 0, discord_name: 'Fox' },
  { player_tag: '#P44DEF', player_name: 'MiniWolf', clan_tag: '#FWA', clan_name: 'Warriors United FWA', weight: 114000, active_strikes: 3, is_filler: false, weight_difference: 1000 },
  { player_tag: '#P55GHI', player_name: 'GreenOak', clan_tag: '#FWA2', clan_name: 'WU FWA Two', weight: 115000, active_strikes: 2, is_filler: false, weight_difference: 0 },
]
const settings = { excluded_roles: [{ id: '769130325460254740', name: 'Strike exempt' }], roles: [{ id: '769130325460254740', name: 'Strike exempt' }, { id: '123456789012345600', name: 'Leave team' }], leaves: [{ discord_id: '123456789012345678', display_name: 'Fox', player_tags: ['#P22ABC', '#8LQQRT'], resume_date: '2026-11-01' }] }
const members = [{ id: '123456789012345678', name: 'Fox', accounts: [{ tag: '#P22ABC', name: 'CastleFox', current_clan_name: 'Warriors United FWA' }, { tag: '#8LQQRT', name: 'LittleThunder', current_clan_name: 'WU North' }] }]
const preview = { preview_id: 'fixture-preview', wars_scanned: 7, complete_wars: 6, incomplete_wars: 1, coverage: [{ clan_name: 'Warriors United FWA', wars: 4, earliest: '2026-09-22T12:00:00Z', latest: now }, { clan_name: 'WU North', wars: 3, earliest: '2026-10-01T12:00:00Z', latest: now }], entries: [{ key: 'war-1-a', player_tag: '#P22ABC', player_name: 'CastleFox', clan_name: 'Warriors United FWA', war_end: now, missed_attacks: 2, will_strike: true }, { key: 'war-2-b', player_tag: '#Q99XYZ', player_name: 'BlueDragon', clan_name: 'WU North', war_end: now, missed_attacks: 1, will_strike: false }] }

const realFetch = window.fetch.bind(window)
window.fetch = async (input, init) => {
  const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url, location.origin).pathname
  if (!path.startsWith('/api/cwl/strikes/')) return realFetch(input, init)
  const method = init?.method || 'GET'
  let data: unknown = { ok: true }
  if (path.endsWith('/overview')) data = { entries, clans: [{ tag: '#FWA', name: 'Warriors United FWA', is_fwa: true }, { tag: '#NORTH', name: 'WU North' }], total: entries.length }
  else if (path.endsWith('/members')) data = { members: members.map(item => ({ ...item, accounts: [] })) }
  else if (path.includes('/members/') && path.endsWith('/accounts')) data = { member: members[0] }
  else if (path.endsWith('/settings')) data = settings
  else if (path.endsWith('/replacements')) data = { candidates }
  else if (path.endsWith('/import/preview')) data = preview
  else if (path.endsWith('/import/apply')) data = { applied: 1, skipped: 0 }
  return new Response(JSON.stringify(data), { status: method === 'POST' ? 201 : 200, headers: { 'Content-Type': 'application/json' } })
}

const fixtureScope = new URLSearchParams(location.search).get('scope')
const fixturePermissions = fixtureScope === 'add' ? ['strikes_add'] : fixtureScope === 'remove' ? ['strikes_remove'] : fixtureScope === 'manage' ? ['strikes'] : ['strikes', 'strikes_add', 'strikes_remove']
createRoot(document.getElementById('root')!).render(<React.StrictMode><main style={{ maxWidth: 1200, margin: "0 auto", padding: "32px 20px" }}><StrikesWorkspace permissions={fixturePermissions} isOwner={false} /></main></React.StrictMode>)
