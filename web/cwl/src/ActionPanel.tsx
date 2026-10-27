import { useId, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { createPortal } from 'react-dom'
import './ActionPanel.css'
import { actionPanelAnchor, backOutOfPanelEntry, installPanelBackHandler, panelHistoryState } from './actionPanelHistory'

type Props = {
  title: string
  children: ReactNode
  onClose: () => void
  busy?: boolean
  trigger: HTMLElement | null
  expandOnSearchFocus?: boolean
  variant?: 'default' | 'side'
}

function focusFallback() {
  const heading = document.querySelector<HTMLElement>('[data-dashboard-focus-fallback], main h1, main [tabindex="-1"]')
  if (!heading) return
  if (!heading.hasAttribute('tabindex')) heading.setAttribute('tabindex', '-1')
  heading.focus({ preventScroll: true })
}

function canRestoreFocus(element: HTMLElement | null) {
  if (!element?.isConnected || element.matches(':disabled')) return false
  if (element.closest('[hidden], [inert], [aria-hidden="true"]')) return false
  return element.getClientRects().length > 0
    && getComputedStyle(element).display !== 'none'
    && getComputedStyle(element).visibility !== 'hidden'
}

export default function ActionPanel({
  title,
  children,
  onClose,
  busy = false,
  trigger,
  expandOnSearchFocus = false,
  variant = 'default',
}: Props) {
  const dialog = useRef<HTMLDialogElement>(null)
  const closeButton = useRef<HTMLButtonElement>(null)
  const busyRef = useRef(busy)
  const onCloseRef = useRef(onClose)
  const panelId = useId()
  const [searchFocused, setSearchFocused] = useState(false)
  const [anchorStyle, setAnchorStyle] = useState<React.CSSProperties>({})
  busyRef.current = busy
  onCloseRef.current = onClose

  useLayoutEffect(() => {
    const modal = dialog.current
    if (!modal) return
    const marker = `action-panel:${panelId}`
    const panelState = panelHistoryState(history.state, marker)
    history.pushState(panelState, '', location.href)
    if (variant === 'default' && trigger) {
      setAnchorStyle(actionPanelAnchor(trigger.getBoundingClientRect(), {
        width: window.innerWidth,
        height: window.innerHeight,
      }) as React.CSSProperties)
    }
    modal.showModal()
    // Focus the explicit close control. Search inputs remain unfocused on open.
    closeButton.current?.focus({ preventScroll: true })

    const removeBackHandler = installPanelBackHandler({
      windowPort: window,
      historyPort: history,
      marker,
      panelState,
      isBusy: () => busyRef.current,
      close: () => onCloseRef.current(),
    })

    return () => {
      removeBackHandler()
      if (modal.open) modal.close()
      const current = history.state && typeof history.state === 'object' ? history.state as Record<string, unknown> : {}
      if (current.wuActionPanel === marker) {
        backOutOfPanelEntry({ windowPort: window, historyPort: history, marker })
      }
      window.requestAnimationFrame(() => {
        if (canRestoreFocus(trigger)) trigger?.focus({ preventScroll: true })
        else focusFallback()
      })
    }
  // Deliberately bind this entry to mount/unmount; prop changes must not add history entries.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const close = () => {
    if (!busy) onClose()
  }

  return createPortal(
    <dialog
      ref={dialog}
      className={`action-panel action-panel-${variant}${searchFocused ? ' is-search-focused' : ''}`}
      style={variant === 'default' ? anchorStyle : undefined}
      aria-labelledby={`${panelId}-title`}
      onCancel={event => {
        event.preventDefault()
        close()
      }}
      onClick={event => {
        if (event.target === dialog.current) close()
      }}
      onFocusCapture={event => {
        if (expandOnSearchFocus && (event.target as HTMLElement).matches('input[type="search"], [data-action-panel-search]')) {
          setSearchFocused(true)
        }
      }}
      onBlurCapture={event => {
        if (expandOnSearchFocus && (event.target as HTMLElement).matches('input[type="search"], [data-action-panel-search]')) {
          setSearchFocused(false)
        }
      }}
    >
      <header className="action-panel-heading">
        <h2 id={`${panelId}-title`}>{title}</h2>
        <button ref={closeButton} type="button" className="action-panel-close" onClick={close} disabled={busy} aria-label="Close panel">Close</button>
      </header>
      <div className="action-panel-content">{children}</div>
    </dialog>,
    document.body,
  )
}
