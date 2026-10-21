import { describe, expect, it } from 'vitest'
import { todoEmptyText, todoTime, visibleTodoRows, type TodoRow, type TodoView } from './todo'
const view: TodoView={ok:true,note:'',notes:[],unavailable:'',incomplete:'',rows:[]}
describe('Todo truthful states',()=>{
 it('never labels unavailable or partial data complete',()=>{
  expect(todoEmptyText({...view,ok:false},'war',false)).toContain('could not be checked')
  expect(todoEmptyText({...view,incomplete:'One failed'},'war',true)).toContain('could not be checked')
  expect(todoEmptyText({...view,unavailable:'No raid weekend'},'raid',false)).toBe('No raid weekend')
  expect(todoEmptyText(view,'games',false)).toContain('Check your progress in-game')
 })
 it('filters selected accounts and distinguishes an empty selection from all',()=>{
  const rows=[{tag:'#A',name:'Alpha',clan_name:'One',ends_at:200,town_hall:16},{tag:'#B',name:'Beta',clan_name:'Two',ends_at:100,town_hall:18}] as TodoRow[]
  expect(visibleTodoRows(rows,null,'','deadline').map(x=>x.tag)).toEqual(['#B','#A'])
  expect(visibleTodoRows(rows,[],'','deadline')).toEqual([])
  expect(visibleTodoRows(rows,['#A'],'one','th').map(x=>x.tag)).toEqual(['#A'])
 })
 it('does not display expired deadlines as time remaining',()=>{
  expect(todoTime(100,101000)).toContain('Time passed')
  expect(todoTime(null,0)).toBe('Time unavailable')
  expect(todoTime(3660,0)).toBe('1h 1m')
 })
})

it('keeps a search handoff exact while allowing normal partial task searches', () => {
  const rows = [{tag:'#ABC',name:'One',clan_tag:'#CLAN'}, {tag:'#ABC2',name:'Two',clan_tag:'#CLAN'}] as TodoRow[]
  expect(visibleTodoRows(rows, null, '#ABC', 'name', true)).toHaveLength(1)
  expect(visibleTodoRows(rows, null, '#CLAN', 'name', true)).toHaveLength(2)
  expect(visibleTodoRows(rows, null, '#ABC', 'name')).toHaveLength(2)
})
