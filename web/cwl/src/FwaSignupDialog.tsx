import { useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import animation from './assets/lazy-way-only.gif'
import './ConfirmDialog.css'
import './FwaSignupDialog.css'

export default function FwaSignupDialog({ onClose }: { onClose: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null)
  const title = useId()
  const [animate, setAnimate] = useState(() => !window.matchMedia('(prefers-reduced-motion: reduce)').matches)
  useLayoutEffect(() => {
    const opener = document.activeElement
    const modal = dialog.current!
    modal.showModal()
    return () => {
      modal.close()
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true })
    }
  }, [])
  return createPortal(<dialog className="confirm-dialog fwa-signup-dialog" ref={dialog}
    aria-labelledby={title} onCancel={event => { event.preventDefault(); onClose() }}>
    <h2 id={title}>Nuh uh uh, your account is in FWA!</h2>
    {animate && <img className="fwa-signup-animation" src={animation} width="220" height="124" alt="A playful finger wag: no, no, no." />}
    <p className="fwa-signup-slogan">LAZY WAY OR NO WAY!</p>
    <p>Accounts currently in an FWA clan can join Lazy CWL only. This account was not selected for Main CWL.</p>
    <div className="confirm-dialog-actions">
      <button className="fwa-animation-control" onClick={() => setAnimate(value => !value)}>{animate ? 'Hide animation' : 'Show animation'}</button>
      <button className="primary" autoFocus onClick={onClose}>Got it</button>
    </div>
  </dialog>, document.body)
}
