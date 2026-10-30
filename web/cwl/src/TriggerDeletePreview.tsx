// Isolated visual fixture for the command trigger deletion controls.
import React from 'react'
import { createRoot } from 'react-dom/client'
import TextCommands from './TextCommands'
import './style.css'

if (!['localhost', '127.0.0.1', '[::1]'].includes(window.location.hostname)) {
  throw new Error('This fixture only runs on loopback.')
}

const rows = [
  {
    command: '!welcome',
    enabled: true,
    delete_trigger: true,
    text: 'Welcome to Warriors United!',
    revision: 'fixture-revision-4',
    last_delete_error: {
      at: '2026-10-30T12:00:00Z',
      channel_id: '123456789012345678',
      reason: 'Missing permissions',
    },
  },
  {
    command: '!legacy',
    enabled: true,
    text: 'A command saved before the deletion setting existed.',
    revision: 'fixture-revision-2',
  },
  {
    command: '!keep',
    enabled: true,
    delete_trigger: false,
    text: 'Keep the trigger message for this command.',
    revision: 'fixture-revision-3',
  },
]

// Fail closed: even an accidental action cannot reach a real API from this page.
window.fetch = async (input, init) => {
  const target =
    typeof input === 'string'
      ? input
      : input instanceof URL
        ? input.href
        : input.url
  const url = new URL(target, window.location.href)
  const method =
    init?.method ?? (input instanceof Request ? input.method : 'GET')
  if (url.origin !== window.location.origin || method !== 'GET') {
    throw new Error(`Fixture blocked ${method} ${url.pathname}`)
  }
  if (url.pathname === '/api/cwl/manage/text-commands') {
    return Response.json({ commands: rows })
  }
  if (url.pathname === '/api/cwl/manage/text-command-roles') {
    return Response.json({ roles: [] })
  }
  throw new Error(`Fixture blocked ${method} ${url.pathname}`)
}

createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <div className="workspace">
      <main>
        <TextCommands onDirty={() => undefined} />
      </main>
    </div>
  </React.StrictMode>,
)
