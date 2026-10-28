import { useEffect, useState } from "react";

/** Shared age cadence for roster and Compare; never fetches location data. */
export default function useLocationNow() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => {
    const clock = setInterval(() => {
      if (document.visibilityState === "visible") setNow(Date.now());
    }, 30_000);
    return () => clearInterval(clock);
  }, []);
  return [now, setNow] as const;
}
