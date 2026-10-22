import { useId, useLayoutEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

type ReviewPool = {
  key: string;
  label: string;
  destination: string;
  roleNames: string[];
  preview: ReactNode;
};

export default function AnnouncementSendReview({
  cycle, version, pools, onCancel, onConfirm,
}: {
  cycle: string;
  version: number | null;
  pools: ReviewPool[];
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const submitted = useRef(false);
  const title = useId();
  useLayoutEffect(() => {
    const opener = document.activeElement;
    const modal = dialog.current!;
    modal.showModal();
    return () => {
      modal.close();
      if (opener instanceof HTMLElement && opener.isConnected) opener.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <dialog ref={dialog} className="announcement-send-review" aria-labelledby={title}
      onCancel={event => { event.preventDefault(); onCancel(); }}
      onKeyDown={event => {
        if (event.key !== 'Tab') return;
        const controls = Array.from(dialog.current!.querySelectorAll<HTMLElement>('button:not(:disabled), a[href], [tabindex="0"]'));
        const first = controls[0], last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last?.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first?.focus(); }
      }}>
      <header><div><h2 id={title}>Review roster announcement{pools.length > 1 ? 's' : ''}</h2>
        <p>{cycle} · Published version {version}</p></div>
        <button autoFocus onClick={onCancel}>Cancel</button></header>
      <p className="announcement-review-warning">Confirming queues {pools.length === 1 ? 'this message' : 'each message separately'}. Selected roles will be notified. Nothing is sent when you cancel.</p>
      {pools.map(pool => <section key={pool.key} aria-label={`${pool.label} send review`}>
        <h3>{pool.label} → #{pool.destination}</h3>
        <p><strong>Roles notified: </strong>{pool.roleNames.length ? pool.roleNames.join(', ') : 'None'}</p>
        {pool.preview}
      </section>)}
      <footer><button className="primary" onClick={() => {
        if (submitted.current) return;
        submitted.current = true;
        onConfirm();
      }}>Queue {pools.length === 1 ? 'announcement' : 'both announcements'}</button></footer>
    </dialog>, document.body,
  );
}
