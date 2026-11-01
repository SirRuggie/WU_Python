import { useEffect, useState } from "react";
import { api, ApiError } from "./api";
import { baseLink, variantLabel, type BankBase } from "./baseBank";

type Details = {
  key: string;
  base_information: string;
  base_upgrade_notes: string;
};
export default function BaseBankCard({
  base,
  onDenied,
}: {
  base: BankBase;
  onDenied: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [details, setDetails] = useState<Details>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => {
    if (!open) return;
    let active = true;
    const controller = new AbortController();
    setDetails(undefined);
    setError("");
    void api<Details>(
      `/bases?level=${encodeURIComponent(base.key)}`,
      "GET",
      undefined,
      { signal: controller.signal },
    )
      .then((value) => {
        if (active) setDetails(value);
      })
      .catch((err) => {
        if (!active || controller.signal.aborted) return;
        if (err instanceof ApiError && [401, 403].includes(err.status))
          onDenied();
        else setError("Couldn't load base details.");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [open, base.key, retry, onDenied]);
  const label = variantLabel(base),
    link = baseLink(base.link);
  return (
    <article
      className="base-bank-card"
      aria-label={`TH${base.town_hall} ${label}`}
    >
      <div className="base-bank-image">
        {base.war_base_image && !imageFailed ? (
          <img
            src={base.war_base_image}
            alt={`TH${base.town_hall} ${label.toLowerCase()} war base`}
            loading="lazy"
            decoding="async"
            referrerPolicy="no-referrer"
            onError={() => setImageFailed(true)}
          />
        ) : (
          <p>Base image coming soon</p>
        )}
      </div>
      <div className="base-bank-card-body">
        <div className="base-bank-tags">
          <span>TH{base.town_hall}</span>
          <span>{label}</span>
        </div>
        {link ? (
          <a
            className="button primary base-bank-copy"
            href={link}
            target="_blank"
            rel="noopener noreferrer"
            aria-label={`Copy TH${base.town_hall} ${label.toLowerCase()} base`}
          >
            Copy base
          </a>
        ) : (
          <p className="base-bank-muted">Base link coming soon</p>
        )}
        {base.has_details && (
          <details onToggle={(event) => setOpen(event.currentTarget.open)}>
            <summary>Details</summary>
            {open &&
              (error ? (
                <p role="alert">
                  {error}{" "}
                  <button onClick={() => setRetry((n) => n + 1)}>
                    Retry details
                  </button>
                </p>
              ) : !details ? (
                <p role="status">Loading details…</p>
              ) : (
                <div className="base-bank-details">
                  {details.base_information && (
                    <p>{details.base_information}</p>
                  )}
                  {details.base_upgrade_notes && (
                    <p>{details.base_upgrade_notes}</p>
                  )}
                </div>
              ))}
          </details>
        )}
      </div>
    </article>
  );
}
