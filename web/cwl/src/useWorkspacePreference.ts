import { useState, type SetStateAction } from 'react'
export default function useWorkspacePreference<T>(key: string, initial: T) {
  const read = () => { try { const value = sessionStorage.getItem(key); return value === null ? initial : JSON.parse(value) as T } catch { return initial } }
  const [value, setValue] = useState<T>(read)
  const update = (next: SetStateAction<T>) => setValue(current => {
    const result = typeof next === 'function' ? (next as (value: T) => T)(current) : next
    try { sessionStorage.setItem(key, JSON.stringify(result)) } catch { /* Storage is optional. */ }
    return result
  })
  return [value, update] as const
}
