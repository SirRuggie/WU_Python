import React from 'react'
import { createRoot } from 'react-dom/client'
import App from './App'
import './style.css'
import './contrast.css'
import './workflowControls.css'
import { registerPushWorker } from './webPush'

// Installation support is passive; notification permission remains opt-in.
if ('serviceWorker' in navigator && window.isSecureContext) {
  void registerPushWorker().catch(() => { /* The dashboard still works when workers are blocked. */ })
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
