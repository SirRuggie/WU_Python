import { useEffect, useState } from "react";
import { knownTownHallIcon, loadTownHallIcons } from "./townHallRegistry";

export default function TownHallIcon({
  level,
}: {
  level: number | null | undefined;
}) {
  const [icons, setIcons] = useState<ReadonlyMap<number, string | null> | null>(
    null,
  );
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  useEffect(() => {
    let active = true;
    void loadTownHallIcons().then((entries) => {
      if (active) setIcons(entries);
    });
    return () => {
      active = false;
    };
  }, []);
  const url =
    level == null ? null : icons?.get(level) || knownTownHallIcon(level);
  const label = level == null ? "Town Hall unknown" : `Town Hall ${level}`;
  return url && failedUrl !== url ? (
    <img
      className="town-hall-icon"
      src={url}
      alt={label}
      title={label}
      width={32}
      height={32}
      loading="lazy"
      onError={() => setFailedUrl(url)}
    />
  ) : (
    <span className="town-hall-fallback" title={label}>
      TH {level ?? "—"}
    </span>
  );
}
