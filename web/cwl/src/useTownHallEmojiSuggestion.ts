import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import {
  suggestedTownHallEmoji,
  type TownHallEmojis,
} from "./TownHallEmojiPicker";

/** Add-page draft suggestion only. This hook never saves a registry. */
export default function useTownHallEmojiSuggestion(
  level: number,
  onChange: (value: string) => void,
) {
  const [data, setData] = useState<TownHallEmojis | null>(null);
  const [status, setStatus] = useState("Loading emojis…");
  const [loading, setLoading] = useState(true);
  const [suggestion, setSuggestion] = useState("");
  const manual = useRef(false);
  const automatic = useRef<string | null>(null);
  const change = useRef(onChange);
  change.current = onChange;
  useEffect(() => {
    const controller = new AbortController();
    void api<TownHallEmojis>("/manage/town-halls/emojis", "GET", undefined, {
      signal: controller.signal,
    })
      .then((result) => {
        if (controller.signal.aborted) return;
        recovered(result);
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setStatus("Emojis could not load. Try again.");
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (!data || manual.current) return;
    const value = suggestedTownHallEmoji(data.emojis, level);
    if (automatic.current !== value) {
      automatic.current = value;
      setSuggestion(value);
      change.current(value);
    }
  }, [data, level]);
  function recovered(result: TownHallEmojis) {
    setData(result);
    setStatus(Object.values(result.errors).join(" "));
  }
  function choose(value: string) {
    manual.current = true;
    setSuggestion("");
    change.current(value);
  }
  return { data, status, loading, choose, suggestion, recovered };
}
