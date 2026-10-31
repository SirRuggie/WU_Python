import { Button } from "./rosterUi/primitives";
import { Send } from "lucide-react";
import { useId, useLayoutEffect, useRef, type ReactNode } from "react";
import { createPortal } from "react-dom";

type ReviewPool = {
  key: string;
  resend?: boolean;
  label: string;
  destination: string;
  roleNames: string[];
  preview: ReactNode;
  clans?: { tag: string; name: string; pages: number }[];
};

export default function AnnouncementSendReview({
  cycle,
  version,
  pools,
  onCancel,
  onConfirm,
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
      if (opener instanceof HTMLElement && opener.isConnected)
        opener.focus({ preventScroll: true });
    };
  }, []);
  return createPortal(
    <dialog
      ref={dialog}
      className="announcement-send-review"
      aria-labelledby={title}
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
      onKeyDown={(event) => {
        if (event.key !== "Tab") return;
        const controls = Array.from(
          dialog.current!.querySelectorAll<HTMLElement>(
            'button:not(:disabled), a[href], [tabindex="0"]',
          ),
        );
        const first = controls[0],
          last = controls[controls.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }}
    >
      <header>
        <div>
          <h2 id={title}>
            Review roster announcement{pools.length > 1 ? "s" : ""}
          </h2>
          <p>
            {cycle} · Published version {version}
          </p>
        </div>
        <Button autoFocus onClick={onCancel}>
          Cancel
        </Button>
      </header>
      <p className="announcement-review-warning">
        Confirming queues{" "}
        {pools.length === 1
          ? "this pool’s post"
          : "each pool’s post separately"}
        . Selected roles will be notified. Nothing is sent when you cancel.
      </p>
      {pools.map((pool) => (
        <section key={pool.key} aria-label={`${pool.label} send review`}>
          {pool.resend && (
            <p role="alert">
              The previous announcement was deleted. Send again will ping the
              configured roles again, followed by fresh clan images and a
              closing note. Earlier image posts stay in Discord.
            </p>
          )}
          <h3>
            {pool.label} → #{pool.destination}
          </h3>
          <p>
            <strong>Roles notified: </strong>
            {pool.roleNames.length ? pool.roleNames.join(", ") : "None"}
          </p>
          <p>
            Posts to #{pool.destination}: 1 announcement
            {pool.roleNames.length
              ? ` (pings ${pool.roleNames.map((name) => `@${name}`).join(", ")})`
              : " (no pings)"}
            , then {pool.clans?.length || 0} clan images in order (no pings),
            then a closing note (no pings).
          </p>
          {!!pool.clans?.length && (
            <details>
              <summary>Clan image order ({pool.clans.length})</summary>
              <ol>
                {pool.clans.map((clan) => (
                  <li key={clan.tag}>
                    {clan.name}
                    {clan.pages > 1
                      ? ` · ${clan.pages} pages in one message`
                      : ""}
                  </li>
                ))}
              </ol>
            </details>
          )}
          {pool.preview}
        </section>
      ))}
      <footer>
        <Button
          icon={Send}
          variant="primary"
          onClick={() => {
            if (submitted.current) return;
            submitted.current = true;
            onConfirm();
          }}
        >
          {pools.some((pool) => pool.resend)
            ? "Send again — ping again"
            : `Queue ${pools.length === 1 ? "announcement" : "both announcements"}`}
        </Button>
      </footer>
    </dialog>,
    document.body,
  );
}
