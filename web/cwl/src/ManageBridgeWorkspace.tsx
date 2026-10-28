import AnnouncementMonth from "./AnnouncementMonth"
import { announcementMonth } from "./announcementMonth"
import ConfirmDialog from "./ConfirmDialog"
import './announcementWorkspace.css'
import AnnouncementSendReview from './AnnouncementSendReview'
import { useReminderLookup } from './useReminderLookups'
import { deliveryLabel, deliveryExplanation, deliveryTime } from './announcementDelivery'
import { useDashboardPermission } from './DashboardPermissions'
import { reconcileAnnouncementSave, type AnnouncementDraft } from './announcementDrafts'
import AnnouncementPreviewDialog from './AnnouncementPreviewDialog'
import DiscordPreview, {type PreviewPart} from './DiscordMessagePreview'
import { useCallback, useEffect, useRef, useState } from 'react'
import { api, ApiError, type Pool } from './api'
import { poolLabel, type AnnouncementChannel } from './announcements'
import ChannelCombobox from './ChannelCombobox'
import { canQueueAnnouncement, dashboardRosterUrl, normalizeManageBridge, shouldPollBridge, type ManageBridge, type ManageDelivery } from './manageBridge'

type Props = { seasonLabel?: string; onDeclaration?: () => void; seasonId: string; publicationVersion: number | null; onDirty?: (dirty: boolean) => void; onBusy?: (busy: boolean) => void }
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

export default function ManageBridgeWorkspace({ seasonId, seasonLabel = "", publicationVersion, onDirty, onBusy, onDeclaration }: Props) {
  const canManage = useDashboardPermission('cwl_send')
  const canDeclare = useDashboardPermission('cwl_roster')
  const [confirmMonth, setConfirmMonth] = useState(false)
  const [sendReview, setSendReview] = useState<Pool[] | null>(null)
  const roles = useReminderLookup<{ id: string; name: string }>('/announcement-roles', 'roles')
  const sending = useRef(false)
  const [bridge, setBridge] = useState<ManageBridge | null>(null)
  const [expandedPreview, setExpandedPreview] = useState<Pool | null>(null)
  const [previewOpen, setPreviewOpen] = useState<Record<Pool, boolean>>({main: false, lazy: false})
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
      const initialize = resetDraft === true || latestBridge.current === null
      if (resetDraft || initialize) {
        const saved = draftFrom(result)
        const reconciliation = initialize || typeof resetDraft !== 'string' ? null : reconcileAnnouncementSave(resetDraft, latestDrafts.current, latestBridge.current ? draftFrom(latestBridge.current) : null, saved)
        setDrafts(reconciliation?.drafts || saved)
        if (!reconciliation?.conflict) setDraftGeneration(result.generation)
        if (initialize) setCycleInput(result.cycle || announcementMonth(seasonLabel))
      }
    } catch (error) { if (id === requestId.current && activeSeason.current === sid) {setBridgeError(errorText(error)); if (error instanceof ApiError && [401,403].includes(error.status)) {setBridge(null);setDrafts(emptyDraft());setDraftGeneration(null)}} }
    finally { if (id === requestId.current && activeSeason.current === sid) setLoading(false) }
  }, [seasonId, seasonLabel])
  const loadChannels = useCallback(async () => {
    try { setChannels((await api<{ channels: AnnouncementChannel[] }>('/announcement-channels')).channels); setChannelsError('') }
    catch (error) { setChannels([]); setChannelsError(errorText(error)) }
  }, [])
  useEffect(() => {
    requestId.current += 1
    activeSeason.current = seasonId
    setSendReview(null); setExpandedPreview(null); setPreviewOpen({main:false,lazy:false}); setTestUrl('');
    setBridge(null); setDrafts(emptyDraft()); setDraftGeneration(null); setCycleInput(''); setNotice(null); setBridgeError(''); setChannelsError('')
    if (seasonId) { void load(true); void loadChannels() }
    return () => { requestId.current++; activeSeason.current = '' }
  }, [seasonId, load, loadChannels])
  const observedPublication = useRef(publicationVersion)
  useEffect(() => {
    if (observedPublication.current === publicationVersion) return
    const previousVersion = observedPublication.current
    observedPublication.current = publicationVersion
    // Publication refreshes must not replace unsaved message drafts.
    setSendReview(null)
    if (previousVersion !== null) setNotice({ kind: 'error', text: 'The published roster changed. Review the new version before sending; your message edits are retained.' })
    void load(false)
  }, [publicationVersion, load])
  useEffect(() => {
    if (!seasonId || busy || sendReview || loading || bridgeError || !shouldPollBridge(bridge)) return
    const timer = window.setTimeout(() => void load(false), 5000)
    return () => window.clearTimeout(timer)
  }, [seasonId, bridge, load, busy, sendReview, loading, bridgeError])
  const setDraft = (pool: Pool, update: Partial<PoolDraft>) => setDrafts(current => ({ ...current, [pool]: { ...current[pool], ...update } }))
  const unsaved = (pool: Pool) => {
    if (!bridge) return false
    const saved = draftFrom(bridge)[pool]
    const current = drafts[pool]
    return saved.channel_id !== current.channel_id || saved.body !== current.body || saved.roster_url !== current.roster_url
  }
  const dirty = !!bridge && (pools.some(unsaved) || cycleInput !== (bridge.cycle || announcementMonth(seasonLabel)))
  useEffect(() => {onBusy?.(busy || !!sendReview); return () => onBusy?.(false)}, [busy, sendReview, onBusy])
  useEffect(() => { onDirty?.(dirty); return () => onDirty?.(false) }, [dirty, onDirty])
  useEffect(() => { if (!dirty) return; const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); event.returnValue = '' }; window.addEventListener('beforeunload', warn); return () => window.removeEventListener('beforeunload', warn) }, [dirty])
  const reviewRefresh = () => {
    if (dirty && !window.confirm('Discard unsaved CWL settings edits and load the latest Manage settings?')) return
    setNotice(null); void load(true); void loadChannels()
  }
  const bindCycle = async () => {
    if (!canManage || !seasonId || busy || loading || !!bridgeError || !/^\d{4}-(0[1-9]|1[0-2])$/.test(cycleInput)) { setNotice({ kind: 'error', text: 'Choose a CWL month in YYYY-MM format.' }); return }
    setConfirmMonth(false)
    const sid = seasonId
    setBusy(true); setNotice(null)
    try {
      await api(`/seasons/${encodeURIComponent(sid)}/manage-bridge/bind`, 'POST', { cycle: cycleInput })
      if (activeSeason.current === sid) { await load(true); setNotice({ kind: 'success', text: `Season bound to Manage CWL settings ${cycleInput}. Review both messages before sending.` }) }
    } catch (error) { if (activeSeason.current === sid) setNotice({ kind: 'error', text: errorText(error) }) }
    finally { setBusy(false) }
  }
  const save = async (pool: Pool) => {
    if (!canManage || loading || bridgeError || !bridge?.generation || !seasonId || busy || draftGeneration !== bridge.generation || !unsaved(pool)) return
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
    if (!canManage || !bridge || busy || loading || bridgeError || !testChannel) return
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
  const readyBoth = canManage && !bridgeError && !!bridge && !busy && !loading && !channelsError && draftGeneration === bridge.generation && pools.every(pool => channels.some(channel => channel.id === drafts[pool].channel_id) && canQueueAnnouncement(bridge, pool, drafts[pool].channel_id, unsaved(pool)))
  const sendBoth = async () => {
    if (!bridge || !readyBoth || sending.current) return
    sending.current = true
    setSendReview(null)
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
    sending.current = false
    setBusy(false)
  }
  const send = async (pool: Pool) => {
    if (sending.current || !canManage || bridgeError || channelsError || loading || !bridge || !seasonId || busy || !canQueueAnnouncement(bridge, pool, drafts[pool].channel_id, unsaved(pool)) || draftGeneration !== bridge.generation) return
    const version = bridge.published_version!
    const channelId = bridge.pools[pool].channel_id!
    sending.current = true
    setSendReview(null)
    const sid = seasonId
    setBusy(true); setNotice(null)
    try {
      const result = await api<{ delivery: ManageDelivery }>(`/seasons/${encodeURIComponent(sid)}/manage-bridge/${pool}/send`, 'POST', { generation: bridge.generation, channel_id: channelId, version })
      if (activeSeason.current !== sid) return
      setBridge(current => current ? { ...current, pools: { ...current.pools, [pool]: { ...current.pools[pool], delivery: result.delivery } } } : current)
      setNotice({ kind: 'success', text: `${poolLabel(pool)} request queued for the bot. Watch the shared Manage delivery status below; no send is confirmed yet.` })
      await load(false)
    } catch (error) { if (activeSeason.current === sid) { setNotice({ kind: 'error', text: error instanceof ApiError && error.status === 409 ? `${error.message} Refresh the Manage status and review before trying again.` : errorText(error) }); await load(false) } }
    finally { sending.current = false; setBusy(false) }
  }
  const preview = (pool: Pool) => bridge ? <DiscordPreview parts={[{type:'container',children:[{type:'text',text:'## '+(bridge.pools[pool].title||'Untitled')},{type:'text',text:drafts[pool].body},...(bridge.pools[pool].role_ids.length?[{type:'text',text:bridge.pools[pool].role_ids.map(id=>`<@&${id}>`).join(' ')} as PreviewPart]:[]),...(bridge.pools[pool].media_url?[{type:'media',items:[{url:bridge.pools[pool].media_url,description:'Roster announcement image'}]} as PreviewPart]:[]),{type:'row',children:bridge.pools[pool].buttons.map((button,index)=>({type:'button',label:button.label,emoji:button.emoji,url:index===0&&drafts[pool].roster_url?drafts[pool].roster_url:button.url}))}]}]}/> : null
  return <section className="manage-bridge-workspace announcement-workspace" aria-labelledby="manage-title">
    <header className="announcement-toolbar">
      <div><h2 id="manage-title">Discord announcements</h2><p>Publishing makes placements visible. Sending notifies members separately.</p></div>
      <button disabled={busy || loading} onClick={reviewRefresh}>Refresh status</button>
    </header>
    {notice && <div className={`notice ${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'}>{notice.text}</div>}
    {bridgeError && <div className="notice error" role="alert">{bridgeError}</div>}
    {channelsError && <div className="notice error" role="alert"><span>Discord channels are unavailable. Sending is disabled.</span><button disabled={busy} onClick={() => void loadChannels()}>Retry channels</button></div>}
    {loading && <p role="status">Checking announcement settings…</p>}
    {bridge && <>
      <div className="announcement-status">
        <strong>{bridge.published_version ? `Published roster · Version ${bridge.published_version}` : 'Publish a roster before sending'}</strong>
        <span>{bridge.worker_ready ? 'Sender ready' : 'Sender unavailable'}</span>
        <span>{bridge.cycle || 'No CWL month selected'}</span>
      </div>
      <AnnouncementMonth key={`${seasonId}:${bridge.cycle}`} value={cycleInput} linked={bridge.cycle}
        disabled={!canManage || busy || loading || !!bridgeError}
        onChange={setCycleInput} onLoad={() => {
          if (bridge.cycle || pools.some(unsaved)) setConfirmMonth(true)
          else void bindCycle()
        }} />
      {bridge.cycle && !bridge.worker_ready && <p className="notice error" role="alert">The bot sender is unavailable. Refresh status before sending.</p>}
      {bridge.cycle && <>
        <div className="manage-pool-tabs" role="tablist" aria-label="Announcement pool">
          {pools.map(pool => <button key={pool} id={`manage-tab-${pool}`} tabIndex={activePool === pool ? 0 : -1}
            onKeyDown={event => {
              const tabs = Array.from(event.currentTarget.parentElement!.querySelectorAll<HTMLButtonElement>('[role="tab"]'))
              const index = pools.indexOf(pool)
              const target = event.key === 'Home' ? 0 : event.key === 'End' ? tabs.length - 1 : event.key === 'ArrowRight' ? (index + 1) % tabs.length : event.key === 'ArrowLeft' ? (index + tabs.length - 1) % tabs.length : -1
              if (target >= 0) {event.preventDefault(); tabs[target].focus()}
            }} type="button" role="tab" aria-selected={activePool === pool} aria-controls={`manage-panel-${pool}`}
            className={activePool === pool ? 'active' : ''} onClick={() => setActivePool(pool)}>
            {poolLabel(pool)}<small>{unsaved(pool) ? 'Unsaved changes' : deliveryLabel(bridge.pools[pool].delivery?.status)}</small>
          </button>)}
        </div>
        <div className="manage-pools">{pools.map(pool => {
          const entry = bridge.pools[pool], draft = drafts[pool], changed = unsaved(pool)
          const delivery = entry.delivery
          const locked = !!delivery && ['sent', 'pending', 'sending', 'uncertain'].includes(delivery.status)
          const canEdit = canManage && !busy && !loading && !bridgeError && !locked && draftGeneration === bridge.generation
          const canSend = canManage && !busy && !loading && !bridgeError && !channelsError && channels.some(channel => channel.id === draft.channel_id) && draftGeneration === bridge.generation && canQueueAnnouncement(bridge, pool, draft.channel_id, changed)
          return <article className="manage-pool" key={pool} id={`manage-panel-${pool}`} role="tabpanel" aria-labelledby={`manage-tab-${pool}`} hidden={activePool !== pool}>
            <div className="announcement-message-heading"><h3>{entry.title || `${poolLabel(pool)} announcement`}</h3><span>{entry.enabled ? 'Enabled' : 'Disabled in CWL settings'}</span></div>
            <div className="announcement-audience">
              <div><small>Audience</small><strong>{poolLabel(pool)} · published roster</strong>
                <span>{entry.role_ids.length ? entry.role_ids.map(id => roles.items.find(role => role.id === id)?.name || `Role ${id}`).join(', ') : 'No roles notified'}</span>
              </div>
              <div><small>Destination</small><strong>{channels.find(channel => channel.id === draft.channel_id)?.name ? `#${channels.find(channel => channel.id === draft.channel_id)?.name}` : draft.channel_id || 'Choose a channel'}</strong><span>{!delivery && deliveryExplanation()}</span></div>
            </div>
            {roles.error && entry.role_ids.length > 0 && <p className="announcement-role-error">Role names unavailable; IDs are shown. <button onClick={roles.retry}>Retry role names</button></p>}
            {delivery && <div className={`manage-delivery delivery-${delivery.status}`} role="status">
              <strong>{deliveryLabel(delivery.status)}</strong>
              <small>{deliveryExplanation(delivery.status)}</small>
              {deliveryTime(delivery) && <small>{deliveryTime(delivery)}</small>}
              {delivery.error && <small>{delivery.error}</small>}
              {safeMessageUrl(delivery.message_url) && <a href={delivery.message_url!} target="_blank" rel="noopener noreferrer">View in Discord ↗</a>}
              {['pending','sending'].includes(delivery.status) && <small>Checking every 5 seconds. No delivery is confirmed yet.</small>}
            </div>}
            <details className="announcement-editor">
              <summary>Edit destination, message &amp; link</summary>
              <div className="announcement-editor-body">
            <ChannelCombobox label={`${poolLabel(pool)} destination`} channels={channels} value={draft.channel_id} disabled={!canEdit || !!channelsError || channels.length === 0} onChange={value => setDraft(pool, {channel_id: value})}/>

                <label>Message<textarea rows={6} maxLength={4000} value={draft.body} disabled={!canEdit} onChange={event => setDraft(pool, {body: event.target.value})}/></label>
                <div className="manage-url-field"><label>Roster button link<input type="url" value={draft.roster_url} disabled={!canEdit} onChange={event => setDraft(pool, {roster_url: event.target.value})}/></label>
                  <button disabled={!canEdit || window.location.protocol !== 'https:'} onClick={() => setDraft(pool, {roster_url: dashboardRosterUrl(window.location.origin, seasonId)})}>Use dashboard link</button>
                </div>
              </div>
            </details>
            <details className="manage-native-preview" onToggle={event => {const open = event.currentTarget.open; setPreviewOpen(current => ({...current, [pool]: open}))}}>
              <summary>Preview message · {entry.role_ids.length} role ping{entry.role_ids.length === 1 ? '' : 's'}</summary>
              {previewOpen[pool] && activePool === pool && <><button className="announcement-expand" onClick={() => setExpandedPreview(pool)}>Expand preview ↗</button>{preview(pool)}</>}
            </details>
            {changed && <p className="inline-reason">Unsaved changes. Save before sending.</p>}
            {draftGeneration !== bridge.generation && <p className="notice error">Settings changed elsewhere. Copy your edits, then refresh and review.</p>}
            <div className="announcement-primary-action">
              {changed ? <button className="primary" disabled={!canEdit || !!channelsError || !channels.length} onClick={() => void save(pool)}>{busy ? 'Saving…' : 'Save message'}</button>
                : <button className="primary" disabled={!canSend} onClick={() => setSendReview([pool])}>{delivery?.status === 'sent' ? 'Already sent' : delivery?.status === 'failed' || delivery?.status === 'stale' ? 'Review and retry send' : 'Review announcement'}</button>}
              <small>{changed ? 'Saving does not send a Discord message.' : 'Confirmation shows the destination. Template role pings notify members.'}</small>
            </div>
            <details className="announcement-test">
              <summary>Test in Discord · no pings</summary>
              <div className="announcement-test-body"><p>Send a separate test without marking the announcement as sent.</p>
                <ChannelCombobox label="Test channel" channels={channels} value={testChannel} disabled={!canManage || busy || !!channelsError} onChange={setTestChannel}/>
                <button disabled={!canManage || busy || loading || !!bridgeError || !testChannel || !!channelsError || draftGeneration !== bridge.generation} onClick={() => void sendTest(pool)}>Send test</button>
                {safeMessageUrl(testUrl) && <a href={testUrl} target="_blank" rel="noopener noreferrer">View test in Discord ↗</a>}
              </div>
            </details>
          </article>
        })}</div>
        <details className="announcement-send-both"><summary>Send both pools together</summary>
          <p>Main and Lazy each send to their saved channel. Each pool sends once per CWL month; republishing does not resend.</p>
          <button disabled={!readyBoth} onClick={() => setSendReview(pools)}>Review both announcements</button>
        </details>
      </>}
    </>}
    {canDeclare && onDeclaration && bridge?.published_version === publicationVersion && pools.some(pool => bridge?.pools[pool].delivery?.status === "sent") && <button className="cwl-next-cue" disabled={busy} onClick={onDeclaration}>Next: Declaration readiness check ›</button>}
    {sendReview && bridge && <AnnouncementSendReview
      cycle={bridge.cycle || ''} version={bridge.published_version}
      pools={sendReview.map(pool => ({
        key: pool, label: poolLabel(pool),
        destination: channels.find(channel => channel.id === drafts[pool].channel_id)?.name || drafts[pool].channel_id,
        roleNames: bridge.pools[pool].role_ids.map(id => roles.items.find(role => role.id === id)?.name || `Role ${id}`),
        preview: preview(pool),
      }))}
      onCancel={() => setSendReview(null)}
      onConfirm={() => { setSendReview(null); if (sendReview.length === 2) void sendBoth(); else void send(sendReview[0]); }}
    />}
    {confirmMonth && <ConfirmDialog
      text={`Change this season's Manage CWL settings from ${bridge?.cycle || 'no month'} to ${cycleInput}? Review both pool templates before sending.${pools.some(unsaved) ? ' Unsaved message edits will be discarded.' : ''}`}
      onCancel={() => setConfirmMonth(false)} onConfirm={() => void bindCycle()} disabled={busy || loading} />}
    {expandedPreview && <AnnouncementPreviewDialog title={`${poolLabel(expandedPreview)} preview`} onClose={() => setExpandedPreview(null)}>{preview(expandedPreview)}</AnnouncementPreviewDialog>}
  </section>
}
