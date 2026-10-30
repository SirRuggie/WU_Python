import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import type { AnnouncementChannel } from "./announcements";

import type { RoleChoice as Choice } from "./RolePicker";
type Choices = {
  roles: Choice[];
  channels: AnnouncementChannel[];
  channelsReady: boolean;
  error: string;
};
const empty: Choices = {
  roles: [],
  channels: [],
  channelsReady: false,
  error: "",
};

export function useClanChoices() {
  const [choices, setChoices] = useState<Choices>(empty);
  const requestGeneration = useRef(0);

  const loadChoices = useCallback(async () => {
    const generation = ++requestGeneration.current;
    setChoices((current) => ({ ...current, channelsReady: false, error: "" }));
    try {
      const result = await api<{
        roles: Choice[];
        channels: AnnouncementChannel[];
      }>("/manage/clan-choices");
      if (generation !== requestGeneration.current) return;
      setChoices({
        roles: result.roles,
        channels: result.channels,
        channelsReady: true,
        error: "",
      });
    } catch (cause) {
      if (generation !== requestGeneration.current) return;
      const error =
        cause instanceof Error
          ? cause.message
          : "Could not load roles and channels.";
      if (cause instanceof ApiError && [401, 403].includes(cause.status)) {
        setChoices({ ...empty, error });
      } else {
        // Keep last-known choices for ordinary outages, clearly marked stale.
        setChoices((current) => ({ ...current, error }));
      }
    }
  }, []);

  useEffect(
    () => () => {
      ++requestGeneration.current;
    },
    [],
  );

  return {
    ...choices,
    choicesError: choices.error,
    loadChoices,
  };
}
