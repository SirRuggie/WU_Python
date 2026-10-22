import {useEffect, useState} from 'react'
import {api} from './api'
import type {MemberOption} from './MemberPicker'
import DiscordContact from './DiscordContact'
import './RosterDiscordIdentity.css'

/** Resolve only the linked identity when the account dialog is mounted. */
export default function RosterDiscordIdentity({userId}: {userId?: string | null}) {
  const [member, setMember] = useState<MemberOption | null>(null)
  const [loading, setLoading] = useState(false)
  const [failed, setFailed] = useState(false)
  const [avatarFailed, setAvatarFailed] = useState(false)
  const [retry, setRetry] = useState(0)
  const validId = !!userId && /^\d{15,22}$/.test(userId)
  useEffect(() => {
    let active = true
    setMember(null)
    setFailed(false)
    setAvatarFailed(false)
    setLoading(validId)
    if (!validId) return
    api<{options: MemberOption[]}>(`/staff-signup-members?id=${encodeURIComponent(userId!)}`)
      .then(result => {if (active) setMember(result.options.find(option => option.id === userId) || null)})
      .catch(() => {if (active) setFailed(true)})
      .finally(() => {if (active) setLoading(false)})
    return () => {active = false}
  }, [userId, validId, retry])

  if (!validId) return <div className="roster-discord-identity"><small>No Discord account linked</small></div>
  const name = member?.display_name || member?.username
  const avatar = !avatarFailed && member?.avatar_url?.startsWith('https://cdn.discordapp.com/') ? member.avatar_url : null
  return <section className="roster-discord-identity" aria-label="Linked Discord member" aria-busy={loading}>
    {avatar ? <img src={avatar} alt="" width={36} height={36} referrerPolicy="no-referrer" onError={() => setAvatarFailed(true)}/>
      : <span className="roster-discord-avatar" aria-hidden="true">{name ? Array.from(name)[0].toUpperCase() : '?'}</span>}
    <div className="roster-discord-person">
      <strong>{name || (loading ? 'Loading Discord member…' : 'Discord member unavailable')}</strong>
      {member?.username && <small>@{member.username}</small>}
      <small className="roster-discord-id">Discord ID: {userId}</small>
      {failed && <small role="status">Could not load profile. <button type="button" onClick={() => setRetry(value => value + 1)}>Retry</button></small>}
    </div>
    <DiscordContact userId={userId} compact/>
  </section>
}
