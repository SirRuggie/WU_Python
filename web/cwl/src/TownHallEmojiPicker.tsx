import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import SearchPicker, { filterOptions, type PickerOption } from "./SearchPicker";

export type TownHallEmoji = {
  value: string;
  name: string;
  source: "server" | "bot";
  image_url: string;
  available: boolean;
};
export type TownHallEmojis = {
  emojis: TownHallEmoji[];
  errors: Partial<Record<"server" | "bot", string>>;
};

export function matchesTownHall(name: string, level: number) {
  return new RegExp(`^th_?${level}(?![0-9])`, "i").test(name);
}

/** Add may suggest an exact bot name; the editor owns whether a choice was manual. */
export function suggestedTownHallEmoji(emojis: TownHallEmoji[], level: number) {
  return (
    emojis.find(
      (emoji) =>
        emoji.source === "bot" &&
        emoji.available &&
        new RegExp(`^th_${level}[a-z]?$`, "i").test(emoji.name),
    )?.value || ""
  );
}

function savedOption(
  value: string,
  unavailable: boolean,
): PickerOption | undefined {
  const match = /^<(a?):([A-Za-z0-9_]{2,32}):([0-9]{15,22})>$/.exec(value);
  if (!match) return undefined;
  return {
    value,
    label: match[2],
    detail: unavailable ? "Emoji no longer available" : undefined,
    icon: (
      <img
        src={`https://cdn.discordapp.com/emojis/${match[3]}.${match[1] ? "gif" : "webp"}?size=48`}
        width={24}
        height={24}
        alt=""
      />
    ),
  };
}

export default function TownHallEmojiPicker({
  value,
  level,
  onChange,
  disabled = false,
  label = "Town Hall emoji",
  endpoint = "/manage/town-halls/emojis",
  onLoaded,
  preloaded,
  preloadPending = false,
  preloadStatus,
}: {
  value: string;
  level: number;
  onChange: (value: string) => void;
  disabled?: boolean;
  label?: string;
  endpoint?: string;
  onLoaded?: (data: TownHallEmojis) => void;
  preloaded?: TownHallEmojis | null;
  preloadPending?: boolean;
  preloadStatus?: string;
}) {
  const [data, setData] = useState<TownHallEmojis | null>(null);
  const currentData = preloaded || data;
  const [status, setStatus] = useState("");
  const flight = useRef<AbortController | null>(null);
  const loadedHandler = useRef(onLoaded);
  loadedHandler.current = onLoaded;
  useEffect(() => () => flight.current?.abort(), []);
  const options: PickerOption[] = (currentData?.emojis || []).map((emoji) => ({
    value: emoji.value,
    label: emoji.name,
    detail: emoji.source === "server" ? "Server emoji" : "Bot emoji",
    disabledNote: emoji.available ? undefined : "Not available in Discord",
    icon: <img src={emoji.image_url} width={24} height={24} alt="" />,
  }));
  async function load() {
    if (disabled || preloadPending || currentData || flight.current) return;
    const controller = new AbortController();
    flight.current = controller;
    setStatus("Loading emojis…");
    try {
      const response = await api<TownHallEmojis>(endpoint, "GET", undefined, {
        signal: controller.signal,
      });
      if (controller.signal.aborted) return;
      setData(response);
      setStatus(Object.values(response.errors).join(" "));
      loadedHandler.current?.(response);
    } catch {
      if (!controller.signal.aborted)
        setStatus("Emojis could not load. Try again.");
    } finally {
      if (flight.current === controller) flight.current = null;
    }
  }
  return (
    <div className="town-hall-emoji-field">
      <SearchPicker
        label={label}
        value={value}
        options={options}
        onChange={onChange}
        placeholder="None"
        searchPlaceholder="Search emoji names"
        emptyText="No matching emojis."
        disabled={disabled}
        clearable
        fallback={savedOption(value, currentData !== null)}
        status={
          preloadPending
            ? "Loading emojis…"
            : status ||
              (preloaded
                ? Object.values(preloaded.errors).join(" ")
                : preloadStatus)
        }
        onOpen={() => void load()}
        search={(query) => {
          const filtered = filterOptions(options, query);
          return query.trim()
            ? filtered
            : [...filtered].sort(
                (a, b) =>
                  Number(matchesTownHall(b.label, level)) -
                  Number(matchesTownHall(a.label, level)),
              );
        }}
      />
      {!value && (
        <p className="field-help">Select the emoji for this Town Hall.</p>
      )}
    </div>
  );
}
