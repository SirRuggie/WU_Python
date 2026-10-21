import { lazy, Suspense, useEffect, useRef, useState } from 'react'
import { api } from '../api'
import { reminderPreviewText } from '../warReminderPreview'
import { timeLabel, type ReminderMessage, type ReminderSettings } from './types'

const DiscordText = lazy(() => import('../DiscordPreview').then(module => ({ default: module.DiscordText })))

type Props = {
  active?: boolean
  base: string
  settings: ReminderSettings
  disabled: boolean
  onDelivered: () => Promise<void>
  onBusy?: (busy: boolean) => void
}

export default function TestPanel({ base, settings, disabled, onDelivered, onBusy, active = true }: Props) {
  const [event, setEvent] = useState('60')
  const [mentionMe, setMentionMe] = useState(true)
  const [useMyAccounts, setUseMyAccounts] = useState(false)
  const [messages, setMessages] = useState<ReminderMessage[]>([])
  const [previewError, setPreviewError] = useState('')
  const [previewLoading, setPreviewLoading] = useState(false)
  const [error, setError] = useState('')
  const [urls, setUrls] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  useEffect(() => { onBusy?.(busy); return () => onBusy?.(false) }, [busy, onBusy])
  const sending = useRef(false)
  const mounted = useRef(true)
  const submission = useRef<{ fingerprint: string; id: string } | null>(null)
  const payload = JSON.stringify({ settings: { ...settings, enabled: false }, event,
    mention_me: mentionMe, use_my_accounts: useMyAccounts })

  useEffect(() => {
    mounted.current = true
    return () => { mounted.current = false }
  }, [])

  useEffect(() => {
    if (!active) return
    let current = true
    setPreviewLoading(true)
    setPreviewError('')
    const timer = setTimeout(() => {
      api<{ messages: ReminderMessage[] }>(base + '/preview', 'POST', JSON.parse(payload))
        .then(result => { if (current) setMessages(result.messages) })
        .catch(e => { if (current) { setMessages([]); setPreviewError(e.message) } })
        .finally(() => { if (current) setPreviewLoading(false) })
    }, 250)
    return () => { current = false; clearTimeout(timer) }
  }, [base, payload, active])

  async function sendTest() {
    if (sending.current) return
    sending.current = true
    setBusy(true)
    setError('')
    setUrls([])
    if (!submission.current || submission.current.fingerprint !== payload) {
      submission.current = { fingerprint: payload, id: crypto.randomUUID() }
    }
    try {
      const result = await api<{ url: string; urls?: string[] }>(base + '/test', 'POST', {
        ...JSON.parse(payload), request_id: submission.current.id,
      })
      submission.current = null
      if (mounted.current) setUrls(result.urls || [result.url])
      // A history refresh failure must not turn a successful send into a retry prompt.
      await onDelivered().catch(() => {})
    } catch (e) {
      if (mounted.current) setError(e instanceof Error ? e.message : 'Could not send test.')
    } finally {
      sending.current = false
      if (mounted.current) setBusy(false)
    }
  }

  const locked = disabled || busy
  const events = [...new Set([...settings.minutes, 60, ...(event === 'start' ? [] : [Number(event)])])].sort((a, b) => b - a)

  return <section className="war-test">
    <p>Test in the channel above without enabling reminders. Each Discord user is mentioned once, with their
      accounts grouped underneath. The message heading includes the clan and time left. Tests also include
      a fictional unlinked account. Counts show attacks used out of those available; test counts are simulated.</p>
    <div className="war-test-controls">
      <label>Preview reminder
        <select disabled={locked} value={event} onChange={e => setEvent(e.target.value)}>
          <option value="start">War started</option>
          {events.map(minutes => <option key={minutes} value={String(minutes)}>{timeLabel(minutes)} before end</option>)}
        </select>
      </label>
      <label className="war-toggle">
        <input type="checkbox" disabled={locked} checked={useMyAccounts} onChange={e => setUseMyAccounts(e.target.checked)} />
        Use my accounts in this clan (up to 5)
      </label>
      <label className="war-toggle">
        <input type="checkbox" disabled={locked} checked={mentionMe} onChange={e => setMentionMe(e.target.checked)} />
        Mention me to test notifications
      </label>
    </div>
    {previewError && <p role="alert">{previewError}</p>}
    {previewLoading ? <p role="status">Updating preview…</p> : <Suspense fallback={<p>Loading preview…</p>}>
      <div className="war-discord-preview">
        <div className="war-bot-name">WU Wizard <span>APP</span><small>Sample preview</small></div>
        {messages.map((message, index) => <div className="war-preview-message" key={index}>
          {messages.length > 1 && <small className="war-preview-part">Message {index + 1} of {messages.length}</small>}
          <DiscordText text={reminderPreviewText(message.content)} />
        </div>)}
        {mentionMe && <small>Your Discord mention heads your account group and triggers the test notification.</small>}
      </div>
    </Suspense>}
    {error && <p role="alert">{error}</p>}
    {urls.length > 0 && <p role="status">Test reminder sent. {urls.map((url, index) =>
      <a key={url} href={url} target="_blank" rel="noreferrer">Open{index ? ` part ${index + 1}` : ''} in Discord ↗ </a>)}</p>}
    <button disabled={locked || !settings.channel_id || previewLoading || !!previewError}
      onClick={() => void sendTest()}>{busy ? 'Sending…' : 'Send test to selected channel'}</button>
  </section>
}
