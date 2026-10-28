import { useId, useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";
import "./ConfirmDialog.css";
export default function ConfirmDialog({
  text,
  onCancel,
  onConfirm,
  heading = "Confirm change",
  confirmLabel = "Confirm",
  disabled = false,
  danger = false,
  children,
}: {
  text: string;
  heading?: string;
  confirmLabel?: string;
  disabled?: boolean;
  danger?: boolean;
  children?: ReactNode;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  const submitted = useRef(false);
  const title = useId(),
    description = useId();
  useLayoutEffect(() => {
    const opener = document.activeElement;
    const modal = dialog.current!;
    modal.showModal();
    return () => {
      modal.close();
      if (opener instanceof HTMLElement && opener.isConnected)
        opener.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <dialog
      ref={dialog}
      className="confirm-dialog"
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = Array.from(dialog.current!.querySelectorAll<HTMLElement>(
          'button, a[href], input, select, textarea, summary, [tabindex]',
        )).filter(element => element.tabIndex >= 0 && !element.matches(':disabled')
          && element.getClientRects().length > 0 && !element.closest('[hidden], [inert]'));
        const first = controls[0], last = controls[controls.length - 1];
        if (!first || !last) return;
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }}
      aria-labelledby={title}
      aria-describedby={description}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <h2 id={title}>{heading}</h2>
      <p id={description}>{text}</p>
      {children}
      <div className="confirm-dialog-actions">
        <button autoFocus onClick={onCancel}>
          Cancel
        </button>
        <button
          className={danger ? "confirm-danger" : "primary"}
          disabled={disabled}
          onClick={() => {
            if (disabled || submitted.current) return;
            submitted.current = true;
            onConfirm();
          }}
        >
          {confirmLabel}
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
