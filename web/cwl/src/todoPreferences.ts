import { isTourReadOnly } from "./memberTour/session"
import type { TodoKind } from './todo'
export type TodoPreferences = { tab: TodoKind; selected: string[] | null; sort: string }
const defaults = (): TodoPreferences => ({ tab: 'war', selected: null, sort: 'deadline' })
const key = (userId: string) => `wu-todo-preferences:${userId}`
const returnKey = 'wu-todo-return'
export function readTodoPreferences(userId: string, storage: Pick<Storage, 'getItem'>): TodoPreferences {
  try {
    const value = JSON.parse(storage.getItem(key(userId)) || 'null')
    if (!value || typeof value !== 'object') return defaults()
    return {
      tab: ['war', 'cwl', 'raid', 'games', 'private'].includes(value.tab) ? value.tab : 'war',
      selected: Array.isArray(value.selected) && value.selected.length <= 100 && value.selected.every((tag: unknown) => typeof tag === 'string' && /^#[A-Z0-9]+$/.test(tag)) ? [...new Set<string>(value.selected)] : null,
      sort: ['deadline', 'th', 'name'].includes(value.sort) ? value.sort : 'deadline',
    }
  } catch { return defaults() }
}
export function saveTodoPreferences(userId: string, value: TodoPreferences, storage: Pick<Storage, 'setItem'>): void {
  if (isTourReadOnly()) return
  try { storage.setItem(key(userId), JSON.stringify(value)) } catch { /* Storage can be blocked or full. */ }
}
export function rememberTodoReturn(search: string, storage: Pick<Storage, 'setItem' | 'removeItem'>): void {
  if (new URLSearchParams(search).get('view') === 'todo') storage.setItem(returnKey, 'todo')
  else storage.removeItem(returnKey)
}
export function initialTodoReturn(search: string, storage: Pick<Storage, 'getItem' | 'removeItem'>): boolean {
  const explicit = new URLSearchParams(search).get('view')
  const saved = storage.getItem(returnKey) === 'todo'
  storage.removeItem(returnKey)
  return explicit ? explicit === 'todo' : saved
}
