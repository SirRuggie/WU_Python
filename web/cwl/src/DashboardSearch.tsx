import { useEffect, useState } from "react";
import { api, ApiError, type Account, type Clan, type Session } from "./api";
import { loadAccountDisplay } from "./accountDisplay";
import CwlPageHeader from "./CwlPageHeader";
import GameSearch from "./GameSearch";
export default function DashboardSearch(props: {
  session: Session;
  includeFamily: boolean;
  query: string;
  onQuery: (value: string) => void;
  kind: "all" | "player" | "clan";
  onKind: (value: "all" | "player" | "clan") => void;
  page: number;
  onPage: (page: number) => void;
  onTasks: (tag: string) => void;
}) {
  const [accounts, setAccounts] = useState<Account[]>([]),
    [family, setFamily] = useState<Clan[]>([]);
  const [busy, setBusy] = useState(true),
    [error, setError] = useState(""),
    [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let active = true,
      denied = false;
    setAccounts([]);
    setFamily([]);
    setBusy(true);
    setError("");
    const reject = (failure: unknown): never => {
      if (
        active &&
        failure instanceof ApiError &&
        [401, 403].includes(failure.status)
      ) {
        denied = true;
        setAccounts([]);
        setFamily([]);
        setError("Your dashboard access changed. Sign in again.");
      }
      throw failure;
    };
    void Promise.allSettled([
      loadAccountDisplay(
        (snapshot) => {
          if (active && !denied) setAccounts(snapshot.accounts);
        },
        () => active && !denied,
        attempt > 0,
      ).catch(reject),
      (props.includeFamily
        ? api<{ clans: Clan[] }>("/approved-clans")
        : Promise.resolve({ clans: [] })
      ).catch(reject),
    ]).then(([players, clans]) => {
      if (!active) return;
      const failures = [players, clans].filter((r) => r.status === "rejected");
      if (
        failures.some(
          (r) =>
            r.status === "rejected" &&
            r.reason instanceof ApiError &&
            [401, 403].includes(r.reason.status),
        )
      ) {
        denied = true;
        setAccounts([]);
        setFamily([]);
        setError("Your dashboard access changed. Sign in again.");
      } else {
        if (players.status === "fulfilled") setAccounts(players.value.accounts);
        if (clans.status === "fulfilled") setFamily(clans.value.clans);
        if (failures.length)
          setError("Some family results could not load. Try again.");
      }
      setBusy(false);
    });
    return () => {
      active = false;
    };
  }, [props.session.user.id, props.includeFamily, attempt]);
  return (
    <section className="dashboard-search-workspace">
      <CwlPageHeader
        title={<h1>Search</h1>}
        description="Find players by tag, and clans by name or tag."
      />
      <GameSearch
        session={props.session}
        accounts={accounts}
        family={family}
        familyBusy={busy}
        familyError={error}
        onRetryFamily={() => setAttempt((n) => n + 1)}
        query={props.query}
        onQuery={props.onQuery}
        kind={props.kind}
        onKind={props.onKind}
        page={props.page}
        onPage={props.onPage}
        onTasks={props.onTasks}
      />
    </section>
  );
}
