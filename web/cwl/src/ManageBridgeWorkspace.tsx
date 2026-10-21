import { reconcileAnnouncementSave, type AnnouncementDraft } from './announcementDrafts'
import AnnouncementPreviewDialog from './AnnouncementPreviewDialog'
import DiscordPreview, {type PreviewPart} from './DiscordMessagePreview'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Pool } from './api'
import { poolLabel, type AnnouncementChannel } from './announcements'
import ChannelCombobox from './ChannelCombobox'
import { canQueueAnnouncement, dashboardRosterUrl, normalizeManageBridge, shouldPollBridge, type ManageBridge, type ManageDelivery } from './manageBridge'

type Props = { seasonId: string; publicationVersion: number | null; onDirty?: (dirty: boolean) => void }
type PoolDraft = AnnouncementDraft
type Notice = { kind: 'success' | 'error'; text: string } | null
const pools: Pool[] = ['main', 'lazy']
const emptyDraft = (): Record<Pool, PoolDraft> => ({ main: { channel_id: '', body: '', roster_url: '' }, lazy: { channel_id: '', body: '', roster_url: '' } })
const errorText = (error: unknown) => error instanceof Error ? error.message : 'Manage CWL settings request failed. Try again.'
const draftFrom = (bridge: ManageBridge): Record<Pool, PoolDraft> => ({
  main: { channel_id: bridge.pools.main.channel_id || '', body: bridge.pools.main.body || '', roster_url: bridge.pools.main.roster_url || '' },
  lazy: { channel_id: bridge.pools.lazy.channel_id || '', body: bridge.pools.lazy.body || '', roster_url: bridge.pools.lazy.roster_url || '' },
})
const safeMessageUrl = (url: string | null | undefined) => !!url && /^https:\/\/(discord\.com|ptb\.discord\.com)\/channels\//.test(url)

export default function ManageBridgeWorkspace({ seasonId, publicationVersion, onDirty }: Props) {
  const [bridge, setBridge] = useState<ManageBridge | null>(null)
  const [expandedPreview, setExpandedPreview] = useState<Pool | null>(null)
  const [testChannel, setTestChannel] = useState('')
  const [testUrl, setTestUrl] = useState('')
  const [activePool, setActivePool] = useState<Pool>('main')
  const [channels, setChannels] = useState<AnnouncementChannel[]>([])
  const [drafts, setDrafts] = useState<Record<Pool, PoolDraft>>(emptyDraft)
  const [draftGeneration, setDraftGeneration] = useState<string | null>(null)
  const [cycleInput, setCycleInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [bridgeError, setBridgeError] = useState('')
  const [channelsError, setChannelsError] = useState('')
  const [notice, setNotice] = useState<Notice>(null)
  const requestId = useRef(0)
  const latestBridge = useRef(bridge)
  latestBridge.current = bridge
  const latestDrafts = useRef(drafts)
  latestDrafts.current = drafts
  const activeSeason = useRef(seasonId)
  activeSeason.current = seasonId
  const load = useCallback(async (resetDraft: boolean | Pool = false) => {
    if (!seasonId) return
    const sid = seasonId
    const id = ++requestId.current
    setLoading(true); setBridgeError('')
    try {
      const result = normalizeManageBridge(await api<ManageBridge>(`/seasons/${encodeURIComponent(sid)}/manage-bridge`))
      if (id !== requestId.current || activeSeason.current !== sid) return
      setBridge(result)
      if (resetDraft) {
        const saved = draftFrom(result)
        const reconciliation = resetDraft === true ? null : reconcileAnnouncementSave(resetDraft, latestDrafts.current, latestBridge.current ? draftFrom(latestBridge.current) : null, saved)
        setDrafts(reconciliation?.drafts || saved)
        if (!reconciliation?.conflict) setDraftGeneration(result.generation)
        if (resetDraft === true) setCycleInput(result.cycle || '')
      }
    } catch (error) { if (id === requestId.current && activeSeason.current === sid) setBridgeError(errorText(error)) }
    finally { if (id === requestId.current && activeSeason.current === sid) setLoading(false) }
  }, [seasonId])
  const loadChannels = useCallback(async () => {
    try { setChannels((await api<{ channels: AnnouncementChannel[] }>('/announcement-channels')).channels); setChannelsError('') }
    catch (error) { setChannels([]); setChannelsError(errorText(error)) }
  }, [])
  useEffect(() => {
    requestId.current += 1
    activeSeason.current = seasonId
    setBridge(null); setDrafts(emptyDraft()); setDraftGeneration(null); setCycleInput(''); setNotice(null); setBridgeError(''); setChannelsError('')
    if (seasonId) { void load(true); void loadChannels() }
    return () => { requestId.current++; activeSeason.current = '' }
  }, [seasonId, publicationVersion, load, loadChannels])
  useEffect(() => {
    if (!seasonId || !shouldPollBridge(bridge)) return
    const timer = window.setTimeout(() => void load(false), 5000)
    return () => window.clearTimeout(timer)
  }, [seasonId, bridge, load])
  const setDraft = (pool: Pool, update: Partial<PoolDraft>) => setDrafts(current => ({ ...current, [pool]: { ...current[pool], ...update } }))
  const unsaved = (pool: Pool) => {
    if (!bridge) return false
    const saved = draftFrom(bridge)[pool]
    const current = drafts[pool]
    return saved.channel_id !== current.channel_id || saved.body !== current.body || saved.roster_url !== current.roster_url
  }
  const dirty = !!bridge && pools.some(unsaved)
  useEffect(() => { onDirty?.(dirty); return () => onDirty?.(false) }, [dirty, onDirty])
  useEffect(() => { if (!dirty) return; const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn) }, [dirty])
  const reviewRefresh = () => {
    if (bridge && pools.some(unsaved) && !window.confirm('Discard unsaved CWL settings edits and load the latest Manage settings?')) return
    setNotice(null); void load(true); void loadChannels()
  }
  const bindCycle = async () => {
    if (!seasonId || busy || !/^\d{4}-(0[1-9]|1[0-2])$/.test(cycleInput)) { setNotice({ kind: 'error', text: 'Choose a CWL month in YYYY-MM format.' }); return }
    if (bridge?.cycle && bridge.cycle !== cycleInput && !window.confirm(`Change this season's Manage CWL settings from ${bridge.cycle} to ${cycleInput}? Review both pool templates before sending.`)) return
    const sid = seasonId
    setBusy(true); setNotice(null)
    try {
      await api(`/seasons/${encodeURIComponent(sid)}/manage-bridge/bind`, 'POST', { cycle: cycleInput })
      if (activeSeason.current === sid) { await load(true); setNotice({ kind: 'success', text: `Season bound to Manage CWL settings ${cycleInput}. Review both messages before sending.` }) }
    } catch (error) { if (activeSeason.current === sid) setNotice({ kind: 'error', text: errorText(error) }) }
    finally { setBusy(false) }
  }
  const save = async (pool: Pool) => {
    if (!bridge?.generation || !seasonId || busy || draftGeneration !== bridge.generation || !unsaved(pool)) return
    const source = drafts[pool]
    if (!/^\d{15,22}$/.test(source.channel_id) || !channels.some(channel => channel.id === source.channel_id)) { setNotice({ kind: 'error', text: 'Choose a current Discord guild channel.' }); return }
    if (source.channel_id === drafts[pool === 'main' ? 'lazy' : 'main'].channel_id) { setNotice({ kind: 'error', text: 'Main and Lazy announcements need different channels.' }); return }
    if (!/^https:\/\/[^\s]+$/.test(source.roster_url)) { setNotice({ kind: 'error', text: 'Enter an HTTPS roster button URL before saving.' }); return }
    const sid = seasonId
    setBusy(true); setNotice(null)
    try {
      await api(`/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}`, 'PATCH', { generation: bridge.generation, channel_id: source.channel_id, body: source.body, roster_url: source.roster_url })
      if (activeSeason.current === sid) { await load(pool); setNotice({ kind: 'success', text: `${poolLabel(pool)} Manage message saved. No announcement was sent.` }) }
    } catch (error) { if (activeSeason.current === sid) setNotice({ kind: 'error', text: error instanceof ApiError && error.status === 409 ? `${error.message} Manage settings changed. Copy any unsaved text, then refresh and review before retrying.` : errorText(error) }) }
    finally { setBusy(false) }
  }
  const sendTest = async (pool: Pool) => {
    if (!bridge || busy || !testChannel) return
    const name = channels.find(channel => channel.id === testChannel)?.name || testChannel
    if (!window.confirm(`Send a ${poolLabel(pool)} test to #${name}? No pings will be sent.`)) return
    const sid = seasonId
    setBusy(true); setNotice(null); setTestUrl('')
    try {
      const nonce = Array.from(crypto.getRandomValues(new Uint8Array(12)), byte => byte.toString(16).padStart(2,'0')).join('')
      const result = await api<{url:string}>(`/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}/test`, 'POST', {channel_id:testChannel, request_id:nonce, generation:bridge.generation, body:drafts[pool].body, roster_url:drafts[pool].roster_url})
      if (activeSeason.current === sid) { setTestUrl(result.url); setNotice({kind:'success',text:'Test sent. The real announcement is unchanged.'}) }
    } catch (error) { if (activeSeason.current === sid) setNotice({kind:'error',text:errorText(error)}) }
    finally {setBusy(false)}
  }
  const readyBoth = !!bridge && !busy && !loading && !channelsError && draftGeneration === bridge.generation && pools.every(pool => channels.some(channel => channel.id === drafts[pool].channel_id) && canQueueAnnouncement(bridge, pool, drafts[pool].channel_id, unsaved(pool)))
  const sendBoth = async () => {
    if (!bridge || !readyBoth) return
    const destinations = pools.map(pool => `${poolLabel(pool)} → #${channels.find(channel => channel.id === drafts[pool].channel_id)?.name}`).join('\n')
    if (!window.confirm(`Send both roster announcements?\n${destinations}\nRole pings will notify members.`)) return
    const sid = seasonId
    setBusy(true); setNotice(null)
    const results: string[] = []
    for (const pool of pools) {
      try {
        await api(`/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}/send`, 'POST', { generation: bridge.generation, channel_id: drafts[pool].channel_id, version: bridge.published_version })
        results.push(`${poolLabel(pool)} queued.`)
      } catch (error) {
        results.push(`${poolLabel(pool)}: ${errorText(error)}`)
      }
    }
    if (activeSeason.current === sid) {
      setNotice({ kind: results.every(result => result.endsWith(' queued.')) ? 'success' : 'error', text: results.join(' ') })
      await load(false)
    }
    setBusy(false)
  }
  const send = async (pool: Pool) => {
    if (!bridge || !seasonId || busy || !canQueueAnnouncement(bridge, pool, drafts[pool].channel_id, unsaved(pool)) || draftGeneration !== bridge.generation) return
    const cycle = bridge.cycle!
    const version = bridge.published_version!
    const channelId = bridge.pools[pool].channel_id!
    const channelName = channels.find(channel => channel.id === channelId)?.name || channelId
    if (!window.confirm(`Queue the ${poolLabel(pool)} roster announcement for ${cycle} in #${channelName} using published roster version ${version}? The bot will send it through the existing Manage delivery system. Native role pings in this template will notify members.`)) return
    const sid = seasonId
    setBusy(true); setNotice(null)
    try {
      const result = await api<{ delivery: ManageDelivery }>(`/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}/send`, 'POST', { generation: bridge.generation, channel_id: channelId, version })
      if (activeSeason.current !== sid) return
      setBridge(current => current ? { ...current, pools: { ...current.pools, [pool]: { ...current.pools[pool], delivery: result.delivery } } } : current)
      setNotice({ kind: 'success', text: `${poolLabel(pool)} request queued for the bot. Watch the shared Manage delivery status below; no send is confirmed yet.` })
      await load(false)
    } catch (error) { if (activeSeason.current === sid) { setNotice({ kind: 'error', text: error instanceof ApiError && error.status === 409 ? `${error.message} Refresh the Manage status and review before trying again.` : errorText(error) }); await load(false) } }
    finally { setBusy(false) }
  }
  const preview = (pool: Pool) => bridge ? <DiscordPreview parts={[{type:'container',children:[{type:'text',text:'## '+(bridge.pools[pool].title||'Untitled')},{type:'text',text:drafts[pool].body},...(bridge.pools[pool].role_ids.length?[{type:'text',text:bridge.pools[pool].role_ids.map(id=>`<@&${id}>`).join(' ')} as PreviewPart]:[]),...(bridge.pools[pool].media_url?[{type:'media',items:[{url:bridge.pools[pool].media_url,description:'Roster announcement image'}]} as PreviewPart]:[]),{type:'row',children:bridge.pools[pool].buttons.map((button,index)=>({type:'button',label:button.label,emoji:button.emoji,url:index===0&&drafts[pool].roster_url?drafts[pool].roster_url:button.url}))}]}]}/> : null
  return <section className="manage-bridge-workspace" aria-labelledby="manage-title"><div className="section-heading"><div><p className="eyebrow">Discord</p><h2 id="manage-title">Discord announcement</h2><p>Review Main and Lazy messages before sending. Publishing a roster does not send an announcement.</p></div><button disabled={busy || loading} onClick={reviewRefresh}>Refresh</button></div>
    {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}
    {bridgeError && <div className="notice error" role="alert">{bridgeError}</div>}
    {channelsError && <div className="notice error" role="alert">Discord channels unavailable: {channelsError}. Channel selection and sending are disabled until they load.</div>}
    {loading && <p role="status">Loading Manage CWL settings…</p>}
    {bridge && <><details key={bridge.cycle || 'unbound'} className="card manage-cycle" open={!bridge.cycle}><summary>CWL month: {bridge.cycle || 'Choose month'}</summary><div className="manage-cycle-fields"><p>Choose the CWL month for this season.</p><label>CWL month<input type="month" value={cycleInput} disabled={busy} onChange={event => setCycleInput(event.target.value)} /></label><button disabled={busy || !cycleInput || cycleInput === bridge.cycle} onClick={() => void bindCycle()}>{bridge.cycle ? 'Change CWL month' : 'Load CWL month'}</button></div></details>
      {bridge.cycle && !bridge.worker_ready && <div className="notice error" role="alert">The bot sender is unavailable. You can edit messages or send a test. Refresh to check again.</div>}
      {!bridge.cycle && <div className="card empty"><p>Choose a CWL month to load the Main and Lazy messages.</p></div>}
      {bridge.cycle && <><div className="manage-bridge-summary"><strong>{bridge.worker_ready ? 'Bot sender ready' : 'Bot sender unavailable'}</strong><span>CWL month {bridge.cycle} · {bridge.published_version ? `roster version ${bridge.published_version}` : 'publish a roster first'}</span><small>Each pool sends once for this CWL month. Republished web versions do not resend automatically.</small></div><div className="manage-pool-tabs" role="tablist" aria-label="Announcement pool">{pools.map(pool => <button key={pool} id={`manage-tab-${pool}`} tabIndex={activePool === pool ? 0 : -1} onKeyDown={event => { const tabs = Array.from(event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]')); const index = pools.indexOf(pool); const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1; if (target >= 0) { event.preventDefault(); tabs[target].focus() } }} type="button" role="tab" aria-selected={activePool === pool} aria-controls={`manage-panel-${pool}`} className={activePool === pool ? 'active' : ''} onClick={() => setActivePool(pool)}>{poolLabel(pool)}<small>{bridge.pools[pool].delivery?.status || 'Not sent'}</small></button>)}</div><div className="manage-pools">{pools.map(pool => {
        const entry = bridge.pools[pool], draft = drafts[pool], changed = unsaved(pool)
        const delivery = entry.delivery
        const locked = delivery?.status === 'sent' || delivery?.status === 'pending' || delivery?.status === 'sending' || delivery?.status === 'uncertain'
        const canEdit = !busy && !locked && draftGeneration === bridge.generation
        const canSend = !busy && !loading && !channelsError && channels.length > 0 && draftGeneration === bridge.generation && canQueueAnnouncement(bridge, pool, draft.channel_id, changed)
        return <article className="card manage-pool" key={pool} id={`manage-panel-${pool}`} role="tabpanel" aria-labelledby={`manage-tab-${pool}`} hidden={activePool !== pool}><div className="card-heading"><h3>{poolLabel(pool)}</h3><span className="badge">{entry.enabled ? 'Enabled in Manage' : 'Disabled in Manage'}</span></div><p className="small">Message: {entry.title || 'Untitled'}</p><ChannelCombobox label={`${poolLabel(pool)} destination`} channels={channels} value={draft.channel_id} disabled={!canEdit || !!channelsError || channels.length === 0} onChange={value => setDraft(pool, { channel_id: value })} /><details className="announcement-editor"><summary>Edit message and link</summary><div className="announcement-editor-body"><label>Message<textarea rows={7} maxLength={4000} value={draft.body} disabled={!canEdit} onChange={event => setDraft(pool, { body: event.target.value })} /></label><div className="manage-url-field"><label>Roster button link<input type="url" value={draft.roster_url} disabled={!canEdit} onChange={event => setDraft(pool, { roster_url: event.target.value })} placeholder="https://…" /></label><button disabled={!canEdit || window.location.protocol !== 'https:'} onClick={() => setDraft(pool, { roster_url: dashboardRosterUrl(window.location.origin, seasonId) })}>Use dashboard roster link</button></div><p className="small">Members open this link from the announcement.</p><button disabled={!canEdit || !changed || !!channelsError || channels.length === 0} onClick={() => void save(pool)}>Save changes</button></div></details><details className="manage-native-preview"><summary>Message preview</summary><button className="announcement-expand" onClick={() => setExpandedPreview(pool)}>Expand preview ↗</button>{preview(pool)}</details>{changed && <p className="inline-reason">Unsaved changes. Save this message before sending.</p>}{draftGeneration !== bridge.generation && <p className="inline-reason">Manage settings changed. Refresh and review before editing or sending.</p>}<p className="small">Sending includes the role pings and artwork shown in the preview.</p><details className="announcement-test"><summary>Send a test to Discord <span>No pings</span></summary><div className="announcement-test-body"><p>Test this message without pings. This does not change the announcement channel or mark it as sent.</p><ChannelCombobox label="Test channel" channels={channels} value={testChannel} disabled={busy} onChange={setTestChannel} /><button disabled={busy || !testChannel || !!channelsError || draftGeneration !== bridge.generation} onClick={() => void sendTest(pool)}>Send test</button>{testUrl && <a href={testUrl} target="_blank" rel="noopener noreferrer">View test in Discord ↗</a>}</div></details><div className="manage-actions"><button disabled={!canEdit || !changed || !!channelsError || channels.length === 0} onClick={() => void save(pool)}>Save message</button><button className="primary" disabled={!canSend} onClick={() => void send(pool)}>{(delivery?.status === 'failed' || delivery?.status === 'stale') ? 'Retry through Manage' : delivery?.status === 'sent' ? 'Already sent this month' : 'Send announcement'}</button></div>{delivery && <div className="manage-delivery"><strong>Announcement status: {delivery.status}</strong>{delivery.error && <small>{delivery.error}</small>}{delivery.message_url && (safeMessageUrl(delivery.message_url) ? <a href={delivery.message_url} target="_blank" rel="noopener noreferrer">View message in Discord ↗</a> : <small>{delivery.message_url}</small>)}{(delivery.status === 'pending' || delivery.status === 'sending') && <small>Checking delivery status every 5 seconds.</small>}{delivery.status === 'uncertain' && <small>Delivery is not confirmed. Check Discord before sending again.</small>}{delivery.status === 'stale' && <small>Settings changed before sending. Review the message and roster, then try again.</small>}</div>}</article>
      })}</div><section className="announcement-send-both"><h3>Send Main and Lazy</h3><div className="manage-actions"><button disabled={!readyBoth} onClick={() => void sendBoth()}>Send both announcements</button><small>Sends each message to its saved channel. Save any changes first.</small></div></section></>}
    </>}
    {expandedPreview && <AnnouncementPreviewDialog title={`${poolLabel(expandedPreview)} preview`} onClose={() => setExpandedPreview(null)}>{preview(expandedPreview)}</AnnouncementPreviewDialog>}
  </section>
}
