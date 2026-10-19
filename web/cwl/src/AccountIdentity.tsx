import { useState } from 'react'
import type { Session } from './api'

export function AccountIdentity({ user }: { user: Session['user'] }) {
  const [failedUrl, setFailedUrl] = useState<string | null>(null)
  const name = user.display_name || user.username
  const showImage = Boolean(user.avatar_url && failedUrl !== user.avatar_url)
  return <span className="user-pill" title={`${name} (@${user.username})`}>
    {showImage
      ? <img className="user-avatar" src={user.avatar_url!} alt="" referrerPolicy="no-referrer" onError={() => setFailedUrl(user.avatar_url!)} />
      : <span className="user-avatar user-avatar-fallback" aria-hidden="true">{Array.from(name)[0]?.toLocaleUpperCase() || '?'}</span>}
    <span className="user-display-name">{name}</span>
  </span>
}
