import { useEffect, useState } from "react";
import { STORAGE_RECOVERED, STORAGE_UNAVAILABLE } from "./storageStatus";

/** A failed storage request never signs staff out or retries a notification. */
export default function DashboardStorageStatus() {
  const [degraded, setDegraded] = useState<false | "recovering" | "attention">(
    false,
  );
  useEffect(() => {
    const unavailable = (event: Event) =>
      setDegraded((previous) =>
        previous === "attention" ||
        (event as CustomEvent<{ attention?: boolean }>).detail?.attention
          ? "attention"
          : "recovering",
      );
    const recovered = (event: Event) => {
      if ((event as CustomEvent<{ confirmed?: boolean }>).detail?.confirmed)
        setDegraded(false);
    };
    window.addEventListener(STORAGE_UNAVAILABLE, unavailable);
    window.addEventListener(STORAGE_RECOVERED, recovered);
    return () => {
      window.removeEventListener(STORAGE_UNAVAILABLE, unavailable);
      window.removeEventListener(STORAGE_RECOVERED, recovered);
    };
  }, []);
  return degraded ? (
    <div className="notice error" role="alert">
      {degraded === "attention"
        ? "Dashboard storage needs attention. Saves are unavailable; contact an administrator."
        : "Dashboard storage is recovering. Saves are temporarily unavailable."}
    </div>
  ) : null;
}
