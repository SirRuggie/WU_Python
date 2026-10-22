import { useEffect, useRef, useState } from 'react'

/** Keep the mobile drawer keyboard-accessible without changing navigation guards. */
export function useMobileNavigation(open: boolean, close: () => void, enabled: boolean) {
  const drawerRef = useRef<HTMLElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [mobile, setMobile] = useState(() => typeof window !== 'undefined' && window.matchMedia('(max-width: 900px)').matches)
  const closeRef = useRef(close)
  closeRef.current = close

  useEffect(() => {
    const query = window.matchMedia('(max-width: 900px)')
    const update = () => {
      setMobile(query.matches)
      if (!query.matches) closeRef.current()
    }
    query.addEventListener('change', update)
    return () => query.removeEventListener('change', update)
  }, [])

  useEffect(() => {
    if (!enabled || !mobile || !open) return
    const drawer = drawerRef.current
    if (!drawer) return
    const controls = () => Array.from(drawer.querySelectorAll<HTMLElement>(
      'button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex="0"]',
    )).filter(element => element.getClientRects().length > 0 && !element.closest('[hidden], [inert]'))
    const first = () => controls()[0] || drawer
    first().focus()
    const keydown = (event: KeyboardEvent) => {
      // Native dialogs own keyboard focus while they are open.
      if (document.querySelector('dialog[open]')) return
      if (event.key === 'Escape') {
        event.preventDefault()
        closeRef.current()
      }
      if (event.key !== 'Tab') return
      const items = controls()
      const target = document.activeElement
      const atStart = target === items[0] || !drawer.contains(target)
      const atEnd = target === items[items.length - 1] || !drawer.contains(target)
      if (!items.length || (event.shiftKey ? atStart : atEnd)) {
        event.preventDefault()
        const next = (event.shiftKey ? items[items.length - 1] : items[0]) || drawer
        next.focus()
      }
    }
    document.addEventListener('keydown', keydown)
    return () => {
      document.removeEventListener('keydown', keydown)
      // A desktop resize hides the trigger; do not move focus to a hidden button.
      if (triggerRef.current?.getClientRects().length) triggerRef.current.focus()
    }
  }, [enabled, mobile, open])

  return { drawerRef, triggerRef, mobile }
}
