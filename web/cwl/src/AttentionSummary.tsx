import { useId } from 'react'
import './AttentionSummary.css'

export type AttentionItem = {
  title: string
  detail?: string
  action?: { label: string; onClick: () => void; disabled?: boolean }
  technicalDetail?: string
  detailsLabel?: string
}

/** A compact recovery list for states that need a user action. */
export default function AttentionSummary({ items, urgent = false }: { items: AttentionItem[]; urgent?: boolean }) {
  const headingId = useId()
  if (!items.length) return null

  return <section className="attention-summary" role={urgent ? "alert" : "status"} aria-labelledby={headingId}>
    <h2 id={headingId}>Needs attention</h2>
    <ul>
      {items.map((item, index) => <li key={item.title + index}>
        <div className="attention-summary-copy">
          <strong>{item.title}</strong>
          {item.detail && <p>{item.detail}</p>}
          {item.technicalDetail && <details><summary>{item.detailsLabel || 'Technical details'}</summary><p>{item.technicalDetail}</p></details>}
        </div>
        {item.action && <button type="button" disabled={item.action.disabled} onClick={item.action.onClick}>{item.action.label}</button>}
      </li>)}
    </ul>
  </section>
}
