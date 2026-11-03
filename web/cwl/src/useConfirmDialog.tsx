import { useCallback, useLayoutEffect, useRef, useState } from "react";
import ConfirmDialog from "./ConfirmDialog";

type Request = {
  text: string;
  label: string;
  resolve: (confirmed: boolean) => void;
};

// Reuse the shared modal while callers retain ownership of their mutation guards.
// A second opener cannot replace a pending decision; unmount always means Cancel.
export default function useConfirmDialog(scope?: string) {
  const pending = useRef<Request | null>(null);
  const [request, setRequest] = useState<Request | null>(null);
  const mounted = useRef(true);
  useLayoutEffect(() => {
    mounted.current = true;
    setRequest(null);
    return () => {
      mounted.current = false;
      pending.current?.resolve(false);
      pending.current = null;
    };
  }, [scope]);
  const confirm = useCallback(
    (text: string, label: string): Promise<boolean> => {
      if (!mounted.current || pending.current) return Promise.resolve(false);
      return new Promise((resolve) => {
        const next = { text, label, resolve };
        pending.current = next;
        setRequest(next);
      });
    },
    [],
  );
  const settle = (confirmed: boolean) => {
    const current = pending.current;
    if (!current) return;
    pending.current = null;
    setRequest(null);
    current.resolve(confirmed);
  };
  return {
    confirm,
    dialog: request ? (
      <ConfirmDialog
        text={request.text}
        confirmLabel={request.label}
        onCancel={() => settle(false)}
        onConfirm={() => settle(true)}
      />
    ) : null,
  };
}
