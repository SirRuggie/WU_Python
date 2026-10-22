import { useState } from 'react'

export default function AccessAvatar({name, kind, url}: {
  name: string; kind: 'user' | 'role'; url?: string | null
}) {
  const [failed, setFailed] = useState<string | null>(null)
  const safeUrl = url?.startsWith('https://cdn.discordapp.com/') ? url : null
  return kind === 'user' && safeUrl && failed !== safeUrl
    ? <img className="access-avatar" src={safeUrl} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(safeUrl)} />
    : <span className="access-avatar access-avatar-fallback" aria-hidden="true">{kind === 'role' ? '@' : Array.from(name)[0]?.toUpperCase() || '?'}</span>
}
