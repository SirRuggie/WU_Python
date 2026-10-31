import { useEffect, useRef, useState } from "react";
import { api } from "./api";

type Setting = { channel_id: string; channel_name: string; revision: number };
const path = "/manage/announcement-test-channel";

/** A per-send choice remains local unless staff explicitly check the save option. */
export default function useAnnouncementTestChannel(allowed: boolean) {
  const [channel, setChannel] = useState("");
  const [makeDefault, setMakeDefault] = useState(false);
  const [setting, setSetting] = useState<Setting | null>(null);
  const [error, setError] = useState("");
  const [refresh, setRefresh] = useState(0);
  const edited = useRef(false);
  const generation = useRef(0);
  useEffect(() => {
    const current = ++generation.current;
    setSetting(null);
    setError("");
    if (!allowed) {
      setChannel("");
      setMakeDefault(false);
      return;
    }
    void api<Setting>(path)
      .then((value) => {
        if (current !== generation.current) return;
        setSetting(value);
        if (!edited.current) setChannel(value.channel_id);
      })
      .catch((e) => {
        if (current === generation.current) setError((e as Error).message);
      });
    return () => {
      generation.current++;
    };
  }, [allowed, refresh]);
  async function saveDefault() {
    if (!makeDefault) return;
    if (!allowed || !setting)
      throw new Error(
        "Reload the saved test channel before making this the default.",
      );
    const current = generation.current;
    const value = await api<Setting>(path, "PUT", {
      channel_id: channel,
      expected_revision: setting.revision,
    });
    if (current !== generation.current)
      throw new Error("Test channel view changed; review again.");
    setSetting(value);
    setMakeDefault(false);
    setError("");
  }
  return {
    channel,
    setChannel: (value: string) => {
      edited.current = true;
      setChannel(value);
    },
    makeDefault,
    setMakeDefault,
    saveDefault,
    error,
    reload: () => setRefresh((n) => n + 1),
  };
}
