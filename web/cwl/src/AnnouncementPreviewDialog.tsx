import { useEffect, useRef, type ReactNode } from 'react'
import { createPortal } from 'react-dom'

export default function AnnouncementPreviewDialog({ title, children, onClose }: {title: string; children: ReactNode; onClose: () => void}) {
  const ref = useRef<HTMLDialogElement>(null)
  useEffect(() => { const dialog = ref.current; dialog?.showModal(); return () => dialog?.close() }, [])
  return createPortal(<dialog className="announcement-preview-dialog" ref={ref} onCancel={onClose} onClose={onClose} aria-labelledby="announcement-preview-title"><header><h2 id="announcement-preview-title">{title}</h2><button autoFocus onClick={onClose}>Close ×</button></header><div className="announcement-preview-body">{children}</div></dialog>, document.body)
}
