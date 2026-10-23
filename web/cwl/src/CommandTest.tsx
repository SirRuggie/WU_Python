import { useEffect, useRef, useState } from 'react'
import { api, ApiError } from './api'
import ChannelCombobox from './ChannelCombobox'
import type { AnnouncementChannel } from './announcements'
import type { Command } from './CommandBuilder'
const requestId = () => crypto.randomUUID().replaceAll('-', '').slice(0, 24)
export default function CommandTest({
  draft,
  disabled,
  onBusy,
}: {
  draft: Command
  disabled: boolean
  onBusy?: (busy: boolean) => void
}) {
  const [channels, setChannels] = useState<AnnouncementChannel[]>([])
  const [channel, setChannel] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(false)
  const [readError, setReadError] = useState('')
  const [error, setError] = useState('')
  const [url, setUrl] = useState('')
  const [uncertain, setUncertain] = useState(false)
  const [review, setReview] = useState(false)
  const nonce = useRef(requestId()),
    sending = useRef(false),
    reading = useRef(false)
  const alive = useRef(true)
  useEffect(() => {
    alive.current = true
    return () => {
      alive.current = false
    }
  }, [])
  useEffect(() => {
    setReview(false)
  }, [draft, channel])
  async function load() {
    if (reading.current) return
    reading.current = true
    setLoading(true)
    setReadError('')
    try {
      const result = await api<{ channels: AnnouncementChannel[] }>(
        '/manage/text-command-test-channels',
      )
      if (alive.current) {
        setChannels(result.channels)
        setChannel((current) =>
          result.channels.some((row) => row.id === current) ? current : '',
        )
      }
    } catch (e) {
      if (alive.current) {
        setChannels([])
        setChannel('')
        setReadError(
          e instanceof Error ? e.message : 'Could not load channels.',
        )
      }
    } finally {
      reading.current = false
      if (alive.current) setLoading(false)
    }
  }
  async function send() {
    if (
      sending.current ||
      disabled ||
      uncertain ||
      !review ||
      !channels.some((row) => row.id === channel)
    )
      return
    sending.current = true
    setBusy(true)
    onBusy?.(true)
    setReview(false)
    setError('')
    setUrl('')
    try {
      const result = await api<{ url: string }>(
        '/manage/text-command-test',
        'POST',
        { values: draft, channel_id: channel, request_id: nonce.current },
      )
      setUrl(result.url)
      nonce.current = requestId()
    } catch (e) {
      // Validation/authorization failures occur before a delivery claim. Other
      // failures can follow Discord accepting the post, so never replay blindly.
      setUncertain(
        !(
          e instanceof ApiError && [400, 401, 403, 404, 413].includes(e.status)
        ),
      )
      setError(
        e instanceof Error ? e.message : 'Delivery could not be confirmed.',
      )
    } finally {
      sending.current = false
      setBusy(false)
      onBusy?.(false)
    }
  }
  return (
    <details
      className="card command-test"
      onToggle={(e) => {
        if (e.currentTarget.open && !channels.length) void load()
      }}
    >
      <summary>Test in Discord</summary>
      <p className="small">
        Posts this draft without saving it. Pings and interactive controls are
        disabled.
      </p>
      {loading && <p role="status">Loading channels…</p>}
      {readError && (
        <p role="alert">
          {readError}{' '}
          <button
            type="button"
            disabled={loading || busy}
            onClick={() => void load()}
          >
            Retry channels
          </button>
        </p>
      )}
      {!loading && !readError && !channels.length && (
        <p>No available text channels.</p>
      )}
      <ChannelCombobox
        label="Test channel"
        channels={channels}
        value={channel}
        disabled={disabled || busy || uncertain || loading}
        onChange={setChannel}
      />
      {!review && (
        <button
          type="button"
          disabled={disabled || busy || uncertain || !channel}
          onClick={() => setReview(true)}
        >
          {busy ? 'Sending…' : 'Review test'}
        </button>
      )}
      {review && (
        <div className="command-test-review">
          <p>
            Send <strong>{draft.command}</strong> to{' '}
            <strong>#{channels.find((row) => row.id === channel)?.name}</strong>
            ?
          </p>
          <button
            type="button"
            disabled={disabled || busy}
            onClick={() => setReview(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={disabled || busy}
            onClick={() => void send()}
          >
            Send test now
          </button>
        </div>
      )}
      {error && <p role="alert">{error}</p>}
      {uncertain && (
        <p>
          Check the selected Discord channel before making another test. This
          attempt will not be sent again automatically.
        </p>
      )}
      {uncertain && (
        <button
          type="button"
          disabled={busy}
          onClick={() => {
            nonce.current = requestId()
            setUncertain(false)
            setError('')
          }}
        >
          I checked Discord — prepare a new test
        </button>
      )}
      {url && (
        <p role="status">
          Test sent.{' '}
          <a href={url} target="_blank" rel="noreferrer">
            Open in Discord ↗
          </a>
        </p>
      )}
    </details>
  )
}
