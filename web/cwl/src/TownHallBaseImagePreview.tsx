import { useState } from "react";
import { previewUrl } from "./previewFormatting";

export default function TownHallBaseImagePreview({
  value,
  label,
}: {
  value: string;
  label: string;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  const url = previewUrl(value);
  return (
    <div className="town-hall-base-preview">
      {!value ? (
        <span>No image set.</span>
      ) : !url || failed === url ? (
        <span>Image could not load.</span>
      ) : (
        <img
          src={url}
          alt={label}
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(url)}
        />
      )}
    </div>
  );
}
