import type { ManagementSection } from './serverManagement'
import { filterSections } from './serverManagement'
import './ServerSettingsIndex.css'

type Props = {
  sections: ManagementSection[]
  query: string
  onQuery: (value: string) => void
  onOpen: (section: ManagementSection, trigger: HTMLButtonElement) => void
}

export function settingsCategory(section: ManagementSection) {
  if (section.id === 'band_monitor') return 'Connections'
  if (section.id === 'fwa_sync' || section.id === 'fwa_points')
    return 'Monitoring & reminders'
  if (
    section.id === 'fwa_bases' ||
    section.id === 'fwa_weight' ||
    section.id === 'fwa_blacklist'
  )
    return 'Clan resources'
  if (section.id.startsWith('war--') || section.id === 'fwa_war_messages')
    return 'War messages'
  return section.group
}

export default function ServerSettingsIndex({
  sections,
  query,
  onQuery,
  onOpen,
}: Props) {
  const visible = filterSections(sections, query)
  const categories = [...new Set(visible.map(settingsCategory))]
  return (
    <div className="server-settings-index">
      <label>
        Find a setting
        <input
          type="search"
          value={query}
          placeholder="Search tools and settings"
          onChange={(event) => onQuery(event.target.value)}
        />
      </label>
      {categories.map((category) => {
        const items = visible.filter(
          (item) => settingsCategory(item) === category,
        )
        const list = (
          <div className="server-settings-list">
            {items.map((item) => (
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
        )
        return (
          <section key={category}>
            {items.length > 4 ? (
              <details
                key={query ? 'search' : 'browse'}
                open={query ? true : undefined}
              >
                <summary>
                  <strong>{category}</strong>
                  <span>{items.length} settings</span>
                </summary>
                {list}
              </details>
            ) : (
              <>
                <h3>{category}</h3>
                {list}
              </>
            )}
          </section>
        )
      })}
      {!visible.length && (
        <div className="empty">
          <p>
            {query
              ? 'No settings match this search.'
              : 'No settings are available for your access.'}
          </p>
          {query && <button onClick={() => onQuery('')}>Clear search</button>}
        </div>
      )}
    </div>
  )
}
