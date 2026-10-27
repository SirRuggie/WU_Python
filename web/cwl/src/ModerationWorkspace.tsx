import { useState } from 'react'
import MemberActivityHistory from './MemberActivityHistory'
import ModerationSettings from './ModerationSettings'
import './ModerationWorkspace.css'

type Section = 'history' | 'settings'

export default function ModerationWorkspace({ onDirty }: { onDirty?: (dirty: boolean) => void }) {
  const [section, setSection] = useState<Section>('history')
  const [openedSettings, setOpenedSettings] = useState(false)

  const showSettings = () => {
    setOpenedSettings(true)
    setSection('settings')
  }

  return (
    <section className="moderation-workspace" aria-labelledby="moderation-title">
      <header className="moderation-workspace-heading">
        <div>
          <p className="eyebrow">Server tools</p>
          <h1 id="moderation-title">Moderation</h1>
          <p>Review member events and configure where notices are posted.</p>
        </div>
      </header>
      <nav className="moderation-sections" aria-label="Moderation sections">
        <button
          type="button"
          aria-pressed={section === 'history'}
          onClick={() => setSection('history')}
        >
          Activity history
        </button>
        <button
          type="button"
          aria-pressed={section === 'settings'}
          onClick={showSettings}
        >
          Log settings
        </button>
      </nav>
      <div hidden={section !== 'history'}>
        <MemberActivityHistory active={section === 'history'} />
      </div>
      {openedSettings && (
        <div hidden={section !== 'settings'}>
          <ModerationSettings onDirty={onDirty} />
        </div>
      )}
    </section>
  )
}
