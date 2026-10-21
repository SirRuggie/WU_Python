import { useEffect, useState } from 'react'
export function useClock() {
  const [now, setNow] = useState(Date.now())
  useEffect(() => {
    const update = () => { if (!document.hidden) setNow(Date.now()) }
    const timer = window.setInterval(update, 30000)
    document.addEventListener('visibilitychange', update)
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', update) }
  }, [])
  return now
}
