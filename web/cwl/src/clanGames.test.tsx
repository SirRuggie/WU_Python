import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import ClanGamesSummary from './ClanGamesSummary'
import TodoTaskCard from './TodoTaskCard'
import { withoutGamesScores } from './todoSnapshot'
import type { TodoRow, TodoView, TodoSnapshot } from './todo'

const row: TodoRow = { tag: '#P2Y', name: '<script>Bad</script>', town_hall: 16,
  clan_tag: '#Q2Y', clan_name: 'Clan', used: 2450, total: null, remaining: null,
  starts_at: Date.parse('2026-10-22T08:00:00Z') / 1000, ends_at: Date.parse('2026-10-28T08:00:00Z') / 1000,
  state: 'reported', detail: null }
const view: TodoView = { ok: true, note: '', notes: [], unavailable: '', incomplete: '', rows: [row],
  season: '2026-10', source: 'ClashPerk', checked_at: '2026-10-23T08:00:00Z', event_start: row.starts_at!, event_end: row.ends_at! }
const now = Date.parse('2026-10-23T12:00:00Z')

describe('Clan Games earned points', () => {
  it('shows earned points without a family target and escapes player names', () => {
    const html = renderToStaticMarkup(<TodoTaskCard row={row} kind="games" now={now}/> )
    expect(html).toContain('2,450 points earned')
    expect(html).not.toContain('goal')
    expect(html).not.toContain('<progress')
    expect(html).not.toContain('<script>')
  })
  it('distinguishes unknown, explicit zero and upcoming', () => {
    const render = (changes: Partial<TodoRow>) => renderToStaticMarkup(<TodoTaskCard row={{...row,...changes}} kind="games" now={now}/>)
    expect(render({used:null})).toContain('Not available')
    expect(render({used:0})).toContain('0 points earned')
    expect(render({used:null,state:'upcoming'})).toContain('Not started')
  })
  it('labels the event month, source, check time, and ended state correctly', () => {
    const html = renderToStaticMarkup(<ClanGamesSummary view={view} now={now}/>)
    expect(html).toContain('October 2026')
    expect(html).toContain('ClashPerk')
    expect(html).toContain('Last checked')
    expect(html).toContain('Ends')
    expect(renderToStaticMarkup(<ClanGamesSummary view={view} now={Date.parse('2026-10-30T08:00:00Z')}/>)).toContain('Event ended')
  })
  it('never persists games scores and preserves other task snapshots without mutation', () => {
    const snapshot: TodoSnapshot = {checked_at: view.checked_at!, accounts:[], views:{war:view,cwl:view,raid:view,private:view,games:view}}
    const safe = withoutGamesScores(snapshot)
    expect(safe.views.games.rows).toEqual([])
    expect(safe.views.war).toBe(view)
    expect(snapshot.views.games.rows).toHaveLength(1)
  })
  it('preserves war attack counts and preparation timers', () => {
    const html = renderToStaticMarkup(<TodoTaskCard row={{...row,state:'preparation',used:0,total:2,remaining:2}} kind="war" now={now}/>)
    expect(html).toContain('Preparation day')
    expect(html).toContain('Battle starts in')
    expect(html).toContain('<progress')
    expect(html).not.toContain('points earned')
  })
})
