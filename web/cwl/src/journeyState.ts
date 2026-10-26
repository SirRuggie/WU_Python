import { useEffect, useLayoutEffect, useRef, useState } from 'react'

// View-only state lives in this tab, keyed by signed-in user and destination.
// Never persist signup selections, permission grants or server data here.
const values = new Map<string, unknown>()
export function useJourneyState<T>(key: string, initial: T) {
  const [value, setValue] = useState<T>(() => values.has(key) ? values.get(key) as T : initial)
  useEffect(() => { values.set(key, value) }, [key, value])
  return [value, setValue] as const
}

const positions = new Map<string, number>()
export function useJourneyPosition(key: string, ready: boolean) {
  const [position] = useState(() => positions.get(key) || 0)
  const restored = useRef(false)
  useLayoutEffect(() => {
    const previousRestoration = window.history.scrollRestoration
    window.history.scrollRestoration = 'manual'
    let last = position
    const remember = () => { if (restored.current) last = window.scrollY }
    window.addEventListener('scroll', remember, {passive: true})
    return () => { window.removeEventListener('scroll', remember); positions.set(key, last); window.history.scrollRestoration = previousRestoration }
  }, [key, position])
  useEffect(() => {
    if (!ready || restored.current) return
    const frame = requestAnimationFrame(() => {
      window.scrollTo({top: position, behavior: 'instant'})
      restored.current = true
    })
    return () => cancelAnimationFrame(frame)
  }, [ready, position])
}

export function clearJourneyState() { values.clear(); positions.clear() }
