import { useId, useLayoutEffect, useRef } from "react";
import { createPortal } from "react-dom";
import "./ConfirmDialog.css";
export default function ConfirmDialog({
  text,
  onCancel,
  onConfirm,
}: {
  text: string;
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
        const buttons =
          dialog.current!.querySelectorAll<HTMLButtonElement>("button");
        const first = buttons[0],
          last = buttons[buttons.length - 1];
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
      <h2 id={title}>Confirm change</h2>
      <p id={description}>{text}</p>
      <div className="confirm-dialog-actions">
        <button autoFocus onClick={onCancel}>
          Cancel
        </button>
        <button
          className="primary"
          onClick={() => {
            if (submitted.current) return;
            submitted.current = true;
            onConfirm();
          }}
        >
          Confirm
        </button>
      </div>
    </dialog>,
    document.body,
  );
}
