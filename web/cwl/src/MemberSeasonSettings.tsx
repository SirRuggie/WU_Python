import { useState } from 'react'
import type { Season } from './api'
import './MemberSeasonSettings.css'

type Props = {
  selected?: Season; active?: Season; busy: boolean;
  onShow: () => void; onHide: () => void;
}
export default function MemberSeasonSettings({ selected, active, busy, onShow, onHide }: Props) {
  const [copyStatus, setCopyStatus] = useState('')
  const signupUrl = new URL('/signup', window.location.origin).href
  const copy = async () => {
    try { await navigator.clipboard.writeText(signupUrl); setCopyStatus('Signup link copied.') }
    catch { setCopyStatus('Select the link below and copy its address.') }
  }
  return <section className="member-season-settings" aria-labelledby="member-season-title">
    <h3 id="member-season-title">Season shown to members</h3>
    <p><strong>{active?.label || 'No season visible'}</strong></p>
    <p>Members always open this season. Creating another season does not change it.</p>
    <div className="member-season-actions">
      <button disabled={busy || !selected || selected.status === 'archived' || selected.id === active?.id} onClick={onShow}>
        {selected?.id === active?.id ? 'Selected season is visible' : `Show ${selected?.label || 'selected season'} to members`}
      </button>
      {active && <button disabled={busy} onClick={onHide}>Hide member season</button>}
    </div>
    <div className="member-signup-link">
      <div><strong>Direct signup link</strong><a href="/signup">{signupUrl}</a><small>Use this in Discord. After sign-in, members go straight to signups.</small></div>
      <button onClick={() => void copy()}>Copy signup link</button>
    </div>
    {copyStatus && <p role="status">{copyStatus}</p>}
  </section>
}
