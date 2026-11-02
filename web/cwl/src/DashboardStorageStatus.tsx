import { useEffect, useState } from "react";
import { STORAGE_RECOVERED, STORAGE_UNAVAILABLE } from "./storageStatus";

/** A failed storage request never signs staff out or retries a notification. */
export default function DashboardStorageStatus() {
  const [degraded, setDegraded] = useState(false);
  useEffect(() => {
    const unavailable = () => setDegraded(true);
    const recovered = () => setDegraded(false);
    window.addEventListener(STORAGE_UNAVAILABLE, unavailable);
    window.addEventListener(STORAGE_RECOVERED, recovered);
    return () => {
      window.removeEventListener(STORAGE_UNAVAILABLE, unavailable);
      window.removeEventListener(STORAGE_RECOVERED, recovered);
    };
  }, []);
  return degraded ? (
    <div className="notice error" role="alert">
      Dashboard storage is recovering. Saves are temporarily unavailable.
    </div>
  ) : null;
}
