import { describe, expect, it, vi } from 'vitest'
import { ApiError } from '../api'
import { readWarDetail, type WarDetail } from './WarDetailPanel'

const member = {tag: '#A', name: '<Player>', map_position: 1, town_hall: 16, attacks_used: 1, attacks_total: 2, linked: null}
const attack = {side: 'clan' as const, attacker_tag: '#A', attacker_name: '<Player>', defender_tag: null, defender_name: null, stars: 2, destruction: 87.4, order: 1, duration: 150, linked: null}
const detail: WarDetail = {
  checked_at: '2026-10-26T14:00:00Z', scope: 'mine', kind: 'regular', clan_tag: '#CLAN', war_id: 'war-1', state: 'inWar',
  clan: {tag: '#CLAN', name: 'Clan'}, opponent: {tag: '#ENEMY', name: 'Enemy'}, team_size: 50, attacks_per_member: 2,
  starts_at: 1, ends_at: 2, lineup: {clan: [member], opponent: []}, attacks: [attack, {...attack}], attacks_complete: false,
  lineup_complete: false, warnings: ['Linked accounts could not be checked.'],
}
function response(status: number, body: unknown) {
  return {ok: status >= 200 && status < 300, status, json: async () => body} as Response
}
const request = {clanTag: '#CLAN', type: 'regular' as const, scope: 'mine' as const, warId: 'war-1'}

describe('readWarDetail', () => {
  it('encodes the clan tag, forwards cancellation, and preserves partial and repeated attacks', async () => {
    let url = ''
    const signals: AbortSignal[] = []
    const result = await readWarDetail({...request, signal: new AbortController().signal, onAccessDenied: vi.fn()}, async (input, init) => {
      url = String(input); signals.push(init?.signal as AbortSignal)
      return response(200, detail)
    })
    expect(url).toContain('clan_tag=%23CLAN')
    expect(signals[0]?.aborted).toBe(false)
    expect(result.lineup.clan[0].linked).toBeNull()
    expect(result.attacks).toHaveLength(2)
    expect(result.attacks_complete).toBe(false)
    expect(result.attacks[0].defender_name).toBeNull()
  })

  it('rejects a response for a replaced war with a refreshable 409', async () => {
    await expect(readWarDetail({...request, signal: new AbortController().signal, onAccessDenied: vi.fn()}, async () => response(200, {...detail, war_id: 'war-2'})))
      .rejects.toMatchObject({status: 409, message: expect.stringContaining('war changed')})
  })

  it('notifies the caller on authorization loss and never treats it as an empty log', async () => {
    const denied = vi.fn()
    await expect(readWarDetail({...request, signal: new AbortController().signal, onAccessDenied: denied}, async () => response(403, {error: 'No access'})))
      .rejects.toBeInstanceOf(ApiError)
    expect(denied).toHaveBeenCalledOnce()
  })

  it('rejects malformed nested lineup or attack records instead of rendering them', async () => {
    await expect(readWarDetail({...request, signal: new AbortController().signal, onAccessDenied: vi.fn()}, async () => response(200, {...detail, lineup: {clan: [null], opponent: []}})))
      .rejects.toThrow('incomplete or malformed')
    await expect(readWarDetail({...request, signal: new AbortController().signal, onAccessDenied: vi.fn()}, async () => response(200, {...detail, attacks: [{...attack, stars: {value: 3}}]})))
      .rejects.toThrow('incomplete or malformed')
  })

  it('caps oversized reads and marks the attack list partial', async () => {
    const result = await readWarDetail({...request, signal: new AbortController().signal, onAccessDenied: vi.fn()}, async () => response(200, {...detail, attacks: Array.from({length: 501}, (_, order) => ({...attack, order})), attacks_complete: true}))
    expect(result.attacks).toHaveLength(500)
    expect(result.attacks_complete).toBe(false)
  })
})
