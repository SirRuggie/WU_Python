import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api";
import { defaultTownHall, type BankBase } from "./baseBank";
import BaseBankCard from "./BaseBankCard";
import { loadAccountDisplay } from "./accountDisplay";
import "./BaseBank.css";

export default function BaseBank({
  townHalls,
}: {
  townHalls?: (number | null)[] | null;
}) {
  const [bases, setBases] = useState<BankBase[]>();
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [chosen, setChosen] = useState<number | null>(null);
  const accessLost = useRef(false);
  const denied = useCallback(() => {
    accessLost.current = true;
    setBases(undefined);
    setError("Sign in again to view Base bank.");
  }, []);
  const [linkedHalls, setLinkedHalls] = useState<(number | null)[] | null>(
    null,
  );
  useEffect(() => {
    if (townHalls !== undefined) return;
    let active = true;
    void loadAccountDisplay(
      () => {},
      () => active,
    )
      .then((snapshot) => {
        if (active) setLinkedHalls(snapshot.accounts.map((a) => a.town_hall));
      })
      .catch((err) => {
        if (
          active &&
          err instanceof ApiError &&
          [401, 403].includes(err.status)
        )
          denied();
      });
    return () => {
      active = false;
    };
  }, [townHalls, denied]);
  useEffect(() => {
    let active = true;
    const controller = new AbortController();
    accessLost.current = false;
    setBases(undefined);
    setError("");
    void api<{ bases: BankBase[] }>("/bases", "GET", undefined, {
      signal: controller.signal,
    })
      .then((result) => {
        if (!Array.isArray(result.bases)) throw new Error("Invalid base list");
        if (active && !accessLost.current) setBases(result.bases);
      })
      .catch((err) => {
        if (!active || controller.signal.aborted || accessLost.current) return;
        if (err instanceof ApiError && [401, 403].includes(err.status))
          denied();
        else setError("Couldn't load Base bank. Try again.");
      });
    return () => {
      active = false;
      controller.abort();
    };
  }, [retry, denied]);
  const levels = [...new Set(bases?.map((b) => b.town_hall))].sort(
    (a, b) => b - a,
  );
  const selected =
    chosen !== null && levels.includes(chosen)
      ? chosen
      : defaultTownHall(
          bases || [],
          townHalls === undefined ? linkedHalls : townHalls,
        );
  useEffect(() => {
    document
      .querySelector<HTMLButtonElement>(
        `.base-bank-levels button[aria-pressed="true"]`,
      )
      ?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [selected]);
  return (
    <section className="base-bank" aria-labelledby="base-bank-heading">
      <header>
        <h1 id="base-bank-heading">Base bank</h1>
        <p>Choose your Town Hall, then copy a FWA base.</p>
      </header>
      {error ? (
        <p role="alert">
          {error} <button onClick={() => setRetry((n) => n + 1)}>Retry</button>
        </p>
      ) : !bases ? (
        <p role="status">Loading bases…</p>
      ) : !bases.length ? (
        <p>No bases are available yet. Check back soon.</p>
      ) : (
        <>
          <div
            className="base-bank-levels"
            role="group"
            aria-label="Town Hall level"
          >
            {levels.map((th) => (
              <button
                key={th}
                aria-label={`Town Hall ${th}`}
                aria-pressed={th === selected}
                onClick={() => setChosen(th)}
              >
                {th}
              </button>
            ))}
          </div>
          <div className="base-bank-grid">
            {bases
              .filter((b) => b.town_hall === selected)
              .sort(
                (a, b) =>
                  Number(a.variant !== "merged") -
                  Number(b.variant !== "merged"),
              )
              .map((base) => (
                <BaseBankCard key={base.key} base={base} onDenied={denied} />
              ))}
          </div>
        </>
      )}
    </section>
  );
}
