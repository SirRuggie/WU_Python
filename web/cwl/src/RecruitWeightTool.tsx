import { useEffect, useRef, useState } from "react";
import { api } from "./api";
import { compactWeight, enteredWeight } from "./replacementView";
import type { ActivityAccount } from "./strikeActivityView";

export default function RecruitWeightTool({
  rows,
  onChoose,
}: {
  rows: ActivityAccount[];
  onChoose: (row: ActivityAccount) => void;
}) {
  const [weight, setWeight] = useState(""),
    [error, setError] = useState(""),
    [busy, setBusy] = useState(false),
    [matches, setMatches] = useState<
      {
        player_tag: string;
        player_name: string;
        weight: number;
        clan_name: string;
      }[]
    >([]);
  const current = useRef(0);
  useEffect(
    () => () => {
      current.current++;
    },
    [],
  );
  async function find() {
    const value = Number(weight);
    if (!Number.isFinite(value) || value <= 0) {
      setError("Enter a positive recruit weight.");
      return;
    }
    const amount = enteredWeight(weight);
    const id = ++current.current;
    setBusy(true);
    setError("");
    try {
      const data = await api<{ candidates: typeof matches }>(
        `/strikes/replacements?weight=${Math.round(amount)}&limit=3`,
      );
      if (!Array.isArray(data.candidates))
        throw new Error("Weight matches are incomplete. Try again.");
      if (id === current.current) setMatches(data.candidates);
    } catch (cause) {
      if (id === current.current) {
        setMatches([]);
        setError(
          cause instanceof Error ? cause.message : "Weights are unavailable.",
        );
      }
    } finally {
      if (id === current.current) setBusy(false);
    }
  }
  return (
    <section className="strike-activity-recruit">
      <p>
        Find the three closest eligible replacement weights. Uses all FWA clans
        and Town Halls; list filters do not apply.
      </p>
      <label>
        Recruit weight
        <input
          inputMode="decimal"
          value={weight}
          onChange={(event) => {
            current.current++;
            setBusy(false);
            setMatches([]);
            setError("");
            setWeight(event.target.value);
          }}
          placeholder="149 or 149000"
        />
      </label>
      <button disabled={busy} onClick={() => void find()}>
        {busy ? "Finding…" : "Find closest weights"}
      </button>
      {error && <p role="alert">{error}</p>}
      <ul>
        {matches.map((item) => (
          <li key={item.player_tag}>
            <button
              disabled={!rows.some((row) => row.player_tag === item.player_tag)}
              onClick={() => {
                const row = rows.find(
                  (row) => row.player_tag === item.player_tag,
                );
                if (row) onChoose(row);
              }}
            >
              {item.player_name} · {item.clan_name} ·{" "}
              {compactWeight(item.weight)} · Gap{" "}
              {compactWeight(Math.abs(item.weight - enteredWeight(weight)))}
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}
