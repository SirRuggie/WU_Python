import { useRef, useState } from 'react'
import type { ManagementSection } from './serverManagement'
import { applicationSteps } from './applicationSteps'
import './ApplicationSettingsIndex.css'

type Props = {
  sections: ManagementSection[]
  query: string
  onQuery: (query: string) => void
  onOpen: (section: ManagementSection, trigger: HTMLButtonElement) => void
}

/** One index for the existing editors; never duplicates their save or send flows. */
export default function ApplicationSettingsIndex({
  sections,
  query,
  onQuery,
  onOpen,
}: Props) {
  const [expanded, setExpanded] = useState('')
  const search = useRef<HTMLInputElement>(null)
  const groups = applicationSteps(sections, query)
  return (
    <div className="application-index">
      <label>
        Find an application setting
        <input
          ref={search}
          type="search"
          value={query}
          onChange={(event) => onQuery(event.target.value)}
          placeholder="Messages, questions, channels…"
        />
      </label>
      <p className="small">
        Choose an area, then the item to edit. Saving a message does not publish
        it.
      </p>
      {groups.map((group) => (
        <details
          key={group.id}
          open={!!query || expanded === group.id}
          onToggle={(event) => {
            if (!query && event.currentTarget.open) setExpanded(group.id)
            else if (!query && expanded === group.id)
              setExpanded((current) => (current === group.id ? '' : current))
          }}
        >
          <summary>
            <span>
              <strong>{group.title}</strong>
              <small>{group.description}</small>
            </span>
            <span className="small">{group.items.length}</span>
          </summary>
          <div className="application-setting-list">
            {group.items.map((item) => (
              <button
                key={item.id}
                onClick={(event) => onOpen(item, event.currentTarget)}
              >
                <span>
                  <strong>{item.label}</strong>
                  <small>{item.description}</small>
                </span>
                <span aria-hidden="true">→</span>
              </button>
            ))}
          </div>
        </details>
      ))}
      {!groups.length && (
        <div className="empty">
          <p>
            {query
              ? 'No settings match this search.'
              : 'No application settings are available for your access.'}
          </p>
          {query && (
            <button
              onClick={() => {
                onQuery('')
                search.current?.focus()
              }}
            >
              Clear search
            </button>
          )}
        </div>
      )}
    </div>
  )
}
