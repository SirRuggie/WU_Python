import { useEffect } from 'react'

/** Report draft ownership to dashboard navigation and protect browser reloads. */
export default function useUnsavedWork(dirty: boolean, onDirty?: (dirty: boolean) => void) {
  useEffect(() => {
    onDirty?.(dirty)
    return () => onDirty?.(false)
  }, [dirty, onDirty])
  useEffect(() => {
    if (!dirty) return
    const warn = (event: BeforeUnloadEvent) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])
}
