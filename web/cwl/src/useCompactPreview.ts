import { useCallback, useSyncExternalStore } from 'react'

/** Match the existing editor-pane CSS breakpoint without rendering hidden previews. */
export default function useCompactPreview(maxWidth: number): boolean {
  const query = `(max-width: ${maxWidth}px)`
  const subscribe = useCallback((notify: () => void) => {
    const media = window.matchMedia(query)
    media.addEventListener('change', notify)
    return () => media.removeEventListener('change', notify)
  }, [query])
  const getSnapshot = useCallback(() => window.matchMedia(query).matches, [query])
  return useSyncExternalStore(subscribe, getSnapshot, () => false)
}
