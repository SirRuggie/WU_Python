import { describe, expect, it } from 'vitest'
import { initialTodoReturn, readTodoPreferences, rememberTodoReturn, saveTodoPreferences } from './todoPreferences'
function storage() {
  const values = new Map<string, string>()
  return { getItem: (key: string) => values.get(key) ?? null, setItem: (key: string, value: string) => { values.set(key, value) }, removeItem: (key: string) => { values.delete(key) } }
}
describe('Todo return and preferences', () => {
  it('keeps selections separate between Discord users and preserves explicitly empty selections', () => {
    const store = storage()
    saveTodoPreferences('one', { tab: 'raid', selected: ['#ABC'], sort: 'th' }, store)
    saveTodoPreferences('two', { tab: 'games', selected: [], sort: 'name' }, store)
    expect(readTodoPreferences('one', store)).toEqual({ tab: 'raid', selected: ['#ABC'], sort: 'th' })
    expect(readTodoPreferences('two', store).selected).toEqual([])
    expect(readTodoPreferences('other', store).selected).toBeNull()
  })
  it('recovers from corrupt, invalid and inaccessible browser storage', () => {
    for (const raw of ['broken', '{"tab":"bad","selected":[42],"sort":"bad"}', 'null']) {
      expect(readTodoPreferences('one', { getItem: () => raw })).toEqual({ tab: 'war', selected: null, sort: 'deadline' })
    }
    expect(readTodoPreferences('one', { getItem: () => { throw Error('blocked') } }).tab).toBe('war')
    expect(() => saveTodoPreferences('one', { tab: 'war', selected: null, sort: 'deadline' }, { setItem: () => { throw Error('full') } })).not.toThrow()
  })
  it('returns to Todo once after OAuth without overriding explicit assignment links', () => {
    const store = storage()
    rememberTodoReturn('?view=todo', store)
    expect(initialTodoReturn('', store)).toBe(true)
    expect(initialTodoReturn('', store)).toBe(false)
    rememberTodoReturn('?view=todo', store)
    expect(initialTodoReturn('?view=assignments&season=2', store)).toBe(false)
    expect(initialTodoReturn('?view=todo', store)).toBe(true)
  })
  it('clears an abandoned return when signing in from another page', () => {
    const store = storage()
    rememberTodoReturn('?view=todo', store)
    rememberTodoReturn('', store)
    expect(initialTodoReturn('', store)).toBe(false)
  })
})
