import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import { reportBrowserIssue } from './api'
window.addEventListener('error', () => { void reportBrowserIssue('browser_error') })
window.addEventListener('unhandledrejection', () => { void reportBrowserIssue('unhandled_promise') })
import './style.css'
import './contrast.css'
import './workflowControls.css'
import { registerPushWorker } from './webPush'

// Installation support is passive; notification permission remains opt-in.
if ('serviceWorker' in navigator && window.isSecureContext) {
  void registerPushWorker().catch(() => { /* The dashboard still works when workers are blocked. */ })
}

window.addEventListener('dashboard-issue', ((event: CustomEvent<string>) => {
  let notice = document.getElementById('dashboard-issue-reference')
  if (!notice) {
    notice = document.createElement('div')
    notice.id = 'dashboard-issue-reference'
    notice.className = 'notice error'
    notice.setAttribute('role', 'alert')
    document.body.prepend(notice)
  }
  notice.textContent = `A browser problem was reported. Contact staff with reference: ${event.detail}`
}) as EventListener)

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
