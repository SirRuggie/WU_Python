import { useEffect, useState } from "react";
import { api } from "../api";

export default function UsageLinks({
  tag,
  revision,
}: {
  tag: string;
  revision: string;
}) {
  const [links, setLinks] = useState<{ label: string; href: string }[]>([]);
  const [error, setError] = useState(false);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true;
    setLinks([]);
    setError(false);
    api<{ links: { label: string; href: string }[] }>(
      `/manage/clans/${encodeURIComponent(tag)}/usage`,
    )
      .then((result) => {
        if (active) setLinks(result.links);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
    };
  }, [tag, revision, attempt]);
  if (error)
    return (
      <p role="status">
        Could not load clan links.{" "}
        <button onClick={() => setAttempt((value) => value + 1)}>
          Retry clan links
        </button>
      </p>
    );
  if (!links.length) return null;
  return (
    <nav aria-label="Used by" className="clan-tabs">
      <span>Used by:</span>
      {links.map((link) => (
        <a
          key={link.href}
          href={link.href}
          target="_blank"
          rel="noreferrer"
          aria-label={`${link.label} (opens in a new tab)`}
        >
          {link.label} ↗
        </a>
      ))}
    </nav>
  );
}
