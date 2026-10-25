import { describe, expect, it } from 'vitest'
import { renderToStaticMarkup } from 'react-dom/server'
import TodoActivityStatus from './TodoActivityStatus'
import type { TodoView } from './todo'
const partial: TodoView = { ok: true, rows: [], incomplete: '9 accounts failed; 33 accounts missing', note: '9 accounts failed; 33 accounts missing', notes: ['9 accounts failed','33 accounts missing'], unavailable: '' }
describe('Tasks failure presentation', () => {
  it('renders one notice and deduplicates the screenshot’s repeated warnings', () => {
    const html = renderToStaticMarkup(<TodoActivityStatus view={partial} hasRows={false} unreadable={9} onAffected={()=>{}}/>)
    expect(html.match(/class="todo-warning"/g)).toHaveLength(1)
    expect(html.match(/9 accounts failed/g)).toHaveLength(1)
    expect(html.match(/33 accounts missing/g)).toHaveLength(1)
    expect(html).toContain('<details><summary>Check details</summary>')
    expect(html).toContain('Couldn’t load this activity')
    expect(html).not.toContain('logs are private')
  })
  it('keeps partial results and loading distinct from a successful empty result', () => {
    expect(renderToStaticMarkup(<TodoActivityStatus view={partial} hasRows unreadable={0} onAffected={()=>{}}/>)).toContain('Some tasks are missing')
    expect(renderToStaticMarkup(<TodoActivityStatus view={{...partial,loading:true}} hasRows={false} unreadable={0} onAffected={()=>{}}/>)).toBe('')
    expect(renderToStaticMarkup(<TodoActivityStatus view={{...partial,incomplete:'',note:'',notes:[]}} hasRows={false} unreadable={0} onAffected={()=>{}}/>)).toBe('')
  })
})
