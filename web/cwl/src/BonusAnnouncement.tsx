import { lazy, Suspense, useEffect, useState } from 'react'
import { api } from './api'
const DiscordPreview = lazy(() => import('./DiscordPreview'))
import ChannelCombobox from './ChannelCombobox'
import type { AnnouncementChannel } from './announcements'
import type { SavedDraw } from './bonusRaffle'

type Props = { draw: SavedDraw; disabled: boolean; onSend: (channel: string, retry?: boolean) => void }

export default function BonusAnnouncement({ draw, disabled, onSend }: Props) {
  const [channels, setChannels] = useState<AnnouncementChannel[]>([])
  const [channel, setChannel] = useState('')
  const [error, setError] = useState('')
  const [retry, setRetry] = useState(0)
  const [loading, setLoading] = useState(false)
  const [reviewed, setReviewed] = useState(false)
  useEffect(() => {
    let active = true
    if (draw.delivery) return
    setLoading(true)
    setError('')
    api<{ channels: AnnouncementChannel[] }>('/announcement-channels')
      .then(result => { if (active) setChannels(result.channels) })
      .catch(cause => { if (active) setError(cause.message) })
      .finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [draw.id, !!draw.delivery, retry])
  const delivery = draw.delivery
  return <section className="bonus-announcement">
    <h3>{delivery ? 'Announcement delivery' : 'Send announcement'}</h3>
    {delivery ? <>
      <p role="status"><strong>{delivery.status === 'sent' ? 'Announcement sent' : delivery.status === 'sending' ? 'Delivery in progress or awaiting verification' : `Delivery ${delivery.status}`}</strong></p>
      {delivery.failure && <p role="alert">{delivery.failure}</p>}
      {delivery.status === 'failed' && <button disabled={disabled} onClick={() => onSend(delivery.channel_id, true)}>Retry unsent messages</button>}
      {delivery.status === 'sending' && <p>Refresh to check the result. After an interrupted send, check Discord before taking any further action.</p>}
      <p className="small">Channel {delivery.channel_id} · {delivery.pages.filter(p => p.status === 'sent').length}/{draw.messages.length} messages confirmed</p>
      {delivery.pages.filter(p => p.message_id).map(p => <p key={p.page}><a href={`https://discord.com/channels/644963518025826315/${delivery.channel_id}/${p.message_id}`} target="_blank" rel="noreferrer">View message {p.page + 1} in Discord ↗</a></p>)}
    </> : <>
      <ChannelCombobox label="Announcement channel" channels={channels} value={channel}
        disabled={disabled || loading} onChange={value => { setChannel(value); setReviewed(false) }} />
      {loading && <p role="status">Loading channels…</p>}
      {error && <p role="alert">{error} <button disabled={loading || disabled} onClick={() => setRetry(n => n + 1)}>Retry channels</button></p>}
      <div className="bonus-message-preview" aria-label="Announcement preview">
        {draw.messages.map((message, index) => <Suspense key={index} fallback={<p>Loading preview…</p>}><DiscordPreview label={`Message ${index + 1}`} parts={[{ type: 'text', text: message }]} caption="Announcement preview · No pings" /></Suspense>)}
      </div>
      <label className="bonus-check"><input type="checkbox" checked={reviewed} disabled={disabled || !channel}
        onChange={event => setReviewed(event.target.checked)} /> I reviewed the winners and selected channel.</label>
      <div className="bonus-action-bar"><span>{draw.messages.length} message{draw.messages.length === 1 ? '' : 's'} · No pings</span>
        <button className="primary" disabled={disabled || !reviewed || !channel || !channels.some(c => c.id === channel)} onClick={() => onSend(channel)}>Send announcement</button></div>
    </>}
    <p className="small">Staff must award the bonuses in Clash of Clans. Posting this announcement does not award medals.</p>
  </section>
}
