import { useEffect, useRef, useState } from 'react'
import { api } from '../api'
import ConfirmDialog from '../ConfirmDialog'
import type { ManagementDocument } from '../serverManagement'
import { actionLabels, clanKey, localDate, scheduleValues, type ReturnAction, type ReturnClan } from './model'

type Receipt = { status: string; message: string; status_url?: string; result?: {details?: string} }
type Props = { action: ReturnAction; clans: ReturnClan[]; onClose: () => void; onDone: () => void }
export default function ReturnBatch({action, clans, onClose, onDone}: Props) {
  const [document, setDocument] = useState<ManagementDocument|null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [attempt, setAttempt] = useState(0)
  const [minutes, setMinutes] = useState(String(clans.length === 1 ? clans[0].return_status?.every_minutes || 60 : 60))
  const [start, setStart] = useState(clans.length === 1 && clans[0].return_status?.starts_at ? localDate(clans[0].return_status.starts_at) : '')
  const [end, setEnd] = useState(clans.length === 1 && clans[0].return_status?.expires_at ? localDate(clans[0].return_status.expires_at) : '')
  const [review, setReview] = useState<Record<string,unknown>|null>(null)
  const [receipt, setReceipt] = useState<Receipt|null>(null)
  const requestId = useRef(crypto.randomUUID())
  const submitted = useRef(false)
  const heading = useRef<HTMLHeadingElement>(null)
  const statusUrl = useRef('')
  const alive = useRef(true)
  useEffect(() => { alive.current = true; heading.current?.focus(); return () => {alive.current = false} }, [])
  useEffect(() => {
    let active = true
    setError(''); setDocument(null)
    void api<ManagementDocument>(`/manage/return-bulk/${action}`)
      .then(value => {if(active) setDocument(value)})
      .catch(cause => {if(active) setError(cause.message || 'Could not load this action.')})
    return () => {active = false}
  }, [action, attempt])
  const permitted = new Set(document?.fields.find(field => field.key === 'clans')?.options?.map(option => option.value) || [])
  const changed = document ? clans.filter(clan => !permitted.has(clanKey(clan))) : []
  const pending = receipt?.status === 'pending'
  const captureCount = clans.filter(clan => clan.return_status?.state === 'not_saved').length
  const check = async () => {
    if (!statusUrl.current || busy) return
    setBusy(true); setError('')
    try {
      const next = await api<Receipt>(statusUrl.current)
      if (!alive.current) return
      setReceipt(next)
      if(next.status !== 'pending') onDone()
    } catch(cause) { if(alive.current) setError(cause instanceof Error ? cause.message : 'Could not check status. Do not submit again.') }
    finally {if(alive.current) setBusy(false)}
  }
  useEffect(() => {
    if (!pending) return
    const timer = window.setInterval(() => {if(!window.document.hidden) void check()}, 3000)
    return () => clearInterval(timer)
  })
  const submit = async () => {
    if (!review || !document || submitted.current) return
    submitted.current = true; setBusy(true); setError(''); setReview(null)
    try {
      const result = await api<Receipt>(`/manage/return-bulk/${action}/run`, 'POST', {revision:document.revision,request_id:requestId.current,values:review})
      if(!alive.current) return
      statusUrl.current = result.status_url || ''
      setReceipt(result)
      if(result.status !== 'pending') onDone()
    } catch(cause) {
      if(alive.current) setError((cause instanceof Error ? cause.message : 'Could not confirm the action.')+' If the outcome is uncertain, check Recent actions. Retrying this unchanged review uses the same request ID.')
      // Retain the request identity so transport retries cannot create a new job.
      if(alive.current) submitted.current = false
    } finally {if(alive.current) setBusy(false)}
  }
  return <section className="return-batch card" aria-labelledby="return-batch-heading">
    <div className="section-heading"><h3 id="return-batch-heading" tabIndex={-1} ref={heading}>{actionLabels[action]} · {clans.length} {clans.length === 1 ? 'clan' : 'clans'}</h3><button disabled={busy || pending} onClick={onClose}>{receipt ? 'Done' : 'Cancel'}</button></div>
    <details><summary>Selected clans ({clans.length})</summary><p>{clans.map(clan => clan.clan_name || clan.label).join(' · ')}</p></details>
    {error && <div role="alert" className="notice error">{error}{!document && <button onClick={() => setAttempt(attempt+1)}>Retry options</button>}</div>}
    {!document && !error && <p role="status">Checking saved lists…</p>}
    {changed.length > 0 && <p role="alert">{changed.length} selected clans are no longer available for this action. Cancel and refresh the overview.</p>}
    {receipt ? <div aria-live="polite"><p>{receipt.message}</p>{receipt.result?.details && <pre className="return-results">{receipt.result.details}</pre>}{pending && <button disabled={busy} onClick={() => void check()}>Check status</button>}</div> : <>
      <fieldset disabled={busy || !document || changed.length > 0}>
        {['schedule','start','resume'].includes(action) && <label>Frequency<select value={minutes} onChange={event => setMinutes(event.target.value)}><option value="30">Every 30 minutes</option><option value="60">Every hour</option><option value="120">Every 2 hours</option></select></label>}
        {action === 'schedule' && <><div className="return-date-fields"><label>Start<input type="datetime-local" value={start} onChange={event => setStart(event.target.value)}/></label><label>Stop<input type="datetime-local" value={end} onChange={event => setEnd(event.target.value)}/></label></div><p className="small">Your timezone: {Intl.DateTimeFormat().resolvedOptions().timeZone}. Up to seven days, within each list’s cutoff. These dates replace the selected clans’ schedules; other clans keep theirs.</p><details><summary>Selected clan limits</summary>{clans.map(clan => <p key={clan.id}>{clan.clan_name || clan.label}: list cutoff {clan.return_status?.list_expires_at ? new Date(clan.return_status.list_expires_at).toLocaleString() : 'Checked when saved'}{clan.return_status?.starts_at && ` · Current window ends ${new Date(clan.return_status.expires_at!).toLocaleString()}`}</p>)}</details></>}
        {action === 'start' && <><p>{captureCount ? `${captureCount} clans: capture their current members first. ` : ''}{clans.length > captureCount && `${clans.length-captureCount} clans: keep their saved member lists. `}{captureCount > 0 && 'Only members currently in a clan can be captured; accounts already away are not included in a new list.'}</p><p>Start the selected FWA clans now, then repeat at this frequency. Any future start is replaced. Reminders stop automatically after up to seven days; existing earlier stop times and list cutoffs still apply.</p></>}
        {action === 'save' && <p>Capture current home-clan members before they leave for CWL. This does not send reminders.</p>}
        {action === 'send' && <p>This sends reminders now to the configured return channels. It does not enable automatic reminders.</p>}
        <button className="primary" onClick={() => {
          try {setError(''); setReview({clans:clans.map(clanKey),every_minutes:Number(minutes),...(action === 'schedule' ? scheduleValues(start,end) : {})})}
          catch(cause) {setError(cause instanceof Error ? cause.message : 'Check your dates.')}
        }}>Review {action === 'schedule' ? 'schedule' : 'action'}</button>
      </fieldset>
    </>}
    {review && <ConfirmDialog onCancel={() => setReview(null)} onConfirm={() => void submit()} text={`${actionLabels[action]} for ${clans.map(clan => clan.clan_name || clan.label).join(', ')}?${action === 'schedule' ? ` Start ${new Date(String(review.schedule_start)).toLocaleString()}; stop ${new Date(String(review.schedule_end)).toLocaleString()}; every ${minutes} minutes.` : ''}${action === 'start' ? ` Capture current members for ${captureCount} clans without a list; keep all existing lists. Start now and repeat every ${minutes} minutes. This can send Discord messages immediately and replaces any future start; existing earlier stop times remain.` : ''}${action === 'send' ? ' This sends Discord messages.' : ''}${action === 'schedule' || action === 'start' || action === 'resume' ? ' Automatic reminders will be enabled.' : ''}`}/>}
  </section>
}
