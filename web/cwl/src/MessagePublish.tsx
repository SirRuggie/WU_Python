import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import {
  ManagementRequestIds,
  safeDiscordUrl,
  type ManagementDocument,
} from './serverManagement'
type PublishPage = {
  revision: string
  posting_channel: string | null
  existing_channel?: string | null
  target_url: string | null
  destination_editor: string | null
  actions: { id: string; label: string; endpoint: string }[]
}
const path = (value: string) => value.replace(/^\/api\/cwl(?=\/)/, '')
const message = (error: unknown) =>
  error instanceof Error ? error.message : 'Could not load publishing controls.'
export default function MessagePublish({
  endpoint,
  dirty,
  busy,
  onBusy,
  onDirty,
}: {
  endpoint: string
  dirty: boolean
  busy: boolean
  onBusy: (busy: boolean) => void
  onDirty?: (dirty: boolean) => void
}) {
  const [page, setPage] = useState<PublishPage | null>(null),
    [error, setError] = useState(''),
    [notice, setNotice] = useState(''),
    [loading, setLoading] = useState(true),
    [statusUrl, setStatusUrl] = useState(''),
    [channelEditor, setChannelEditor] = useState<ManagementDocument | null>(
      null,
    ),
    [channels, setChannels] = useState<{ value: string; label: string }[]>([]),
    [channel, setChannel] = useState(''),
    [search, setSearch] = useState('')
  const sending = useRef(false)
  const channelDirty =
    !!channelEditor &&
    channel !==
      String(
        channelEditor.fields.find((field) => field.key === 'channel_id')
          ?.value || '',
      )
  useEffect(() => {
    onDirty?.(channelDirty)
    return () => onDirty?.(false)
  }, [channelDirty, onDirty])
  const ids = useRef(new ManagementRequestIds()),
    alive = useRef(true),
    pendingKey = useRef(''),
    checking = useRef(false)
  async function load() {
    setLoading(true)
    try {
      const result = await api<PublishPage>(path(endpoint))
      if (alive.current) {
        setPage(result)
        setError('')
      }
    } catch (e) {
      if (alive.current) setError(message(e))
    } finally {
      if (alive.current) setLoading(false)
    }
  }
  useEffect(() => {
    alive.current = true
    void load()
    return () => {
      alive.current = false
    }
  }, [endpoint])
  async function check(url: string) {
    if (checking.current) return
    checking.current = true
    onBusy(true)
    let finished = false
    try {
      const result = await api<{
        status: string
        message?: string
        result?: { message?: string; url?: string }
      }>(path(url))
      if (!alive.current) return
      setNotice(
        result.result?.message || result.message || 'Waiting for the bot…',
      )
      if (['done', 'failed', 'uncertain'].includes(result.status)) {
        finished = true
        setStatusUrl('')
        if (result.status === 'done') {
          ids.current.complete(pendingKey.current)
          await load()
        } else
          setError(
            result.message || 'Check the Discord post before trying again.',
          )
      } else setStatusUrl(url)
    } catch (e) {
      if (alive.current) setError(message(e))
    } finally {
      checking.current = false
      if (alive.current && finished) onBusy(false)
    }
  }
  useEffect(() => {
    if (!statusUrl) return
    const timer = window.setInterval(() => void check(statusUrl), 2500)
    return () => window.clearInterval(timer)
  }, [statusUrl])
  async function publish(action: PublishPage['actions'][number]) {
    if (sending.current || !page || dirty || busy || statusUrl) return
    const destination =
      action.id === 'update' ? page.existing_channel : page.posting_channel
    if (
      !window.confirm(
        `${action.label} in ${destination || 'the saved Discord channel'}? This posts the saved message.`,
      )
    )
      return
    sending.current = true
    onBusy(true)
    setError('')
    setNotice('')
    const key = ids.current.key(action.endpoint, page.revision, {})
    pendingKey.current = key
    let queued = false
    try {
      const result = await api<{ status_url?: string; message?: string }>(
        path(action.endpoint),
        'POST',
        { revision: page.revision, request_id: ids.current.get(key) },
      )
      if (!alive.current) return
      setNotice(result.message || 'Queued for publishing.')
      if (result.status_url) {
        queued = true
        setStatusUrl(result.status_url)
      } else {
        ids.current.complete(key)
        await load()
      }
    } catch (e) {
      if (alive.current) setError(message(e))
    } finally {
      sending.current = false
      if (alive.current && !queued) onBusy(false)
    }
  }
  async function editChannel() {
    if (!page?.destination_editor) return
    onBusy(true)
    setError('')
    try {
      const [doc, choices] = await Promise.all([
        api<ManagementDocument>(path(page.destination_editor)),
        api<{ channels: { value: string; label: string }[] }>(
          '/manage/choices',
        ),
      ])
      if (alive.current) {
        setChannelEditor(doc)
        setChannels(choices.channels)
        setChannel(
          String(
            doc.fields.find((field) => field.key === 'channel_id')?.value || '',
          ),
        )
      }
    } catch (e) {
      if (alive.current) setError(message(e))
    } finally {
      if (alive.current) onBusy(false)
    }
  }
  async function saveChannel() {
    if (sending.current || !page?.destination_editor || !channelEditor) return
    sending.current = true
    onBusy(true)
    setError('')
    try {
      await api(path(page.destination_editor), 'PATCH', {
        revision: channelEditor.revision,
        values: { channel_id: channel },
      })
      if (alive.current) {
        setChannelEditor(null)
        await load()
        setNotice('Posting channel saved.')
      }
    } catch (e) {
      if (alive.current) setError(message(e))
    } finally {
      sending.current = false
      if (alive.current) onBusy(false)
    }
  }
  return (
    <section className="manage-publish card" aria-label="Publish message">
      <h3>Publish to Discord</h3>
      {loading && <p role="status">Loading publishing controls…</p>}
      {error && (
        <p className="manage-error" role="alert">
          {error}{' '}
          <button disabled={busy || !!statusUrl} onClick={() => void load()}>
            Refresh publishing
          </button>
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {page && (
        <>
          <p>
            <strong>New post channel:</strong>{' '}
            {page.posting_channel || 'Not selected'}
          </p>
          {safeDiscordUrl(page.target_url || '') && (
            <p>
              <a
                href={safeDiscordUrl(page.target_url!)!}
                target="_blank"
                rel="noopener noreferrer"
              >
                View existing post
                {page.existing_channel ? ' in ' + page.existing_channel : ''} ↗
              </a>
            </p>
          )}
          {page.destination_editor && !channelEditor && (
            <button
              disabled={busy || !!statusUrl}
              onClick={() => void editChannel()}
            >
              Change posting channel
            </button>
          )}
          {channelEditor && (
            <div className="manage-fields">
              <label>
                Find a channel
                <input
                  type="search"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="Channel name"
                />
              </label>
              <label>
                Posting channel
                <select
                  value={channel}
                  disabled={busy}
                  onChange={(event) => setChannel(event.target.value)}
                >
                  <option value="">Choose a channel</option>
                  {channels
                    .filter(
                      (item) =>
                        item.value === channel ||
                        item.label.toLowerCase().includes(search.toLowerCase()),
                    )
                    .map((item) => (
                      <option value={item.value} key={item.value}>
                        {item.label}
                      </option>
                    ))}
                </select>
              </label>
              <div className="manage-categories">
                <button
                  disabled={busy || !channel}
                  onClick={() => void saveChannel()}
                >
                  Save channel
                </button>
                <button
                  disabled={busy}
                  onClick={() => {
                    if (
                      !channelDirty ||
                      window.confirm('Discard the posting channel change?')
                    )
                      setChannelEditor(null)
                  }}
                >
                  Cancel
                </button>
              </div>
            </div>
          )}
          {dirty && (
            <p className="manage-notice">
              Save your message changes before publishing. Preview is always
              available.
            </p>
          )}
          {!page.actions.length && !page.destination_editor && (
            <p>
              This message is posted through ticket setup. You can preview and
              save edits here.
            </p>
          )}
          <div className="manage-categories">
            {page.actions.map((action) => (
              <button
                className={action.id === 'update' ? 'primary' : ''}
                key={action.id}
                disabled={busy || dirty || !!statusUrl || !!channelEditor}
                onClick={() => void publish(action)}
              >
                {action.label}
              </button>
            ))}
          </div>
          {statusUrl && (
            <button onClick={() => void check(statusUrl)}>
              Check publishing status
            </button>
          )}
        </>
      )}
    </section>
  )
}
