import type { Dispatch, RefObject, SetStateAction } from "react";
import AccountLinkHelp from "./AccountLinkHelp";
import AttentionSummary from "./AttentionSummary";
import CwlPageHeader from "./CwlPageHeader";
import CwlPoolTabs from "./CwlPoolTabs";
import MemberSeasonLine from "./MemberSeasonLine";
import SavedSignupStatus from "./SavedSignupStatus";
import SavedSignups from "./SavedSignups";
import SignupReviewHeading from "./SignupReviewHeading";
import SignupWalkthrough from "./SignupWalkthrough";
import TownHallIcon from "./TownHallIcon";
import type { DashboardView } from "./SidebarNavigation";
import type { Account, Pool, Season, Signup } from "./api";
import { memberSignupsOpen } from "./memberSeason";
import type { Draft, SignupSelection, submittedSummary } from "./signup";
import type { SignupMove } from "./signupMoves";

export type Notice = { kind: "success" | "error"; text: string };
export type Completion = {
  seasonId: string;
  seasonLabel: string;
  pool: Pool;
  accounts: ReturnType<typeof submittedSummary>;
  refreshWarning: boolean;
};
const poolName = (pool: Pool | null) =>
  pool === "lazy" ? "Lazy CWL" : pool === "main" ? "Main CWL" : "CWL";

type SignupPageProps = {
  accountError: string;
  accounts: Account[];
  accountsReady: boolean;
  activeCompletion: Completion | null;
  available: Account[];
  changeReviewStep: (step: 1 | 2) => void;
  changeSignupPanel: (panel: "register" | "saved", after?: () => void) => void;
  changeView: (
    next: DashboardView,
    filter?: string,
    kind?: "war" | "cwl",
    panel?: "register" | "saved",
  ) => void;
  choosePool: (next: Pool) => void;
  completionHeadingRef: RefObject<HTMLHeadingElement | null>;
  currentSignupPage: number;
  dataError: string;
  draft: Draft;
  existing: Signup[];
  lastSignupPage: number;
  loadSeasons: () => Promise<void>;
  loadSignup: () => Promise<unknown>;
  loadingData: boolean;
  matchingAccounts: Account[];
  notice: Notice | null;
  pageAccounts: Account[];
  pending: boolean;
  pool: Pool | null;
  poolRemoved: string[];
  registeredHeadingRef: RefObject<HTMLHeadingElement | null>;
  retrySignupRead: () => Promise<void>;
  review: boolean;
  saveSavedSignups: (
    moves: SignupMove[],
  ) => Promise<{ saved: string[]; error: string | null }>;
  savedSignupsLoaded: boolean;
  season: Season | undefined;
  seasonError: string;
  seasonId: string;
  seasonsKnown: boolean;
  seasonsLoading: boolean;
  selected: SignupSelection[];
  selectionHeadingRef: RefObject<HTMLHeadingElement | null>;
  setCompletion: Dispatch<SetStateAction<Completion | null>>;
  setDraft: (next: Draft) => void;
  setFwaBlocked: Dispatch<SetStateAction<boolean>>;
  setPool: Dispatch<SetStateAction<Pool | null>>;
  setPoolRemoved: Dispatch<SetStateAction<string[]>>;
  setReturnToReview: Dispatch<SetStateAction<boolean>>;
  setReview: Dispatch<SetStateAction<boolean>>;
  setSavedSignupDirty: Dispatch<SetStateAction<boolean>>;
  setSignupPage: Dispatch<SetStateAction<number>>;
  setSignupPanel: Dispatch<SetStateAction<"register" | "saved">>;
  setSignupSearch: Dispatch<SetStateAction<string>>;
  setSignupStep: Dispatch<SetStateAction<1 | 2>>;
  showSavedSignups: () => Promise<void>;
  signupPanel: "register" | "saved";
  signupSearch: string;
  signupStep: 1 | 2;
  stepHeadingRef: RefObject<HTMLHeadingElement | null>;
  submit: () => Promise<void>;
  visibleAccounts: Account[];
  withdraw: (rows: Signup[]) => Promise<void>;
};

export default function SignupPage({
  accountError,
  accounts,
  accountsReady,
  activeCompletion,
  available,
  changeReviewStep,
  changeSignupPanel,
  changeView,
  choosePool,
  completionHeadingRef,
  currentSignupPage,
  dataError,
  draft,
  existing,
  lastSignupPage,
  loadSeasons,
  loadSignup,
  loadingData,
  matchingAccounts,
  notice,
  pageAccounts,
  pending,
  pool,
  poolRemoved,
  registeredHeadingRef,
  retrySignupRead,
  review,
  saveSavedSignups,
  savedSignupsLoaded,
  season,
  seasonError,
  seasonId,
  seasonsKnown,
  seasonsLoading,
  selected,
  selectionHeadingRef,
  setCompletion,
  setDraft,
  setFwaBlocked,
  setPool,
  setPoolRemoved,
  setReturnToReview,
  setReview,
  setSavedSignupDirty,
  setSignupPage,
  setSignupPanel,
  setSignupSearch,
  setSignupStep,
  showSavedSignups,
  signupPanel,
  signupSearch,
  signupStep,
  stepHeadingRef,
  submit,
  visibleAccounts,
  withdraw,
}: SignupPageProps) {
  return (
    <>
      <CwlPageHeader
        className="member-signup-head"
        title={<h1>{signupPanel === "saved" ? "My signups" : "Sign up"}</h1>}
      />
      <p className="cwl-page-description">
        {signupPanel === "saved"
          ? "Your saved CWL signups for this season."
          : activeCompletion
            ? "Your season signup is saved."
            : season && !memberSignupsOpen(season)
              ? "View your saved signups and CWL clans."
              : "Sign up your accounts for CWL. Staff will select your CWL clans."}
      </p>
      {((seasonError && !seasonsKnown) ||
        (!activeCompletion && (dataError || accountError))) && (
        <AttentionSummary
          urgent
          items={[
            ...(seasonError && !seasonsKnown
              ? [
                  {
                    title: "CWL season availability could not be checked",
                    detail:
                      "The season list may be out of date. Retry before choosing a season.",
                    technicalDetail: seasonError,
                    action: {
                      label: "Retry seasons",
                      onClick: () => void loadSeasons(),
                      disabled: seasonsLoading,
                    },
                  },
                ]
              : []),
            ...(!activeCompletion && dataError
              ? [
                  {
                    title: accountError
                      ? "Signup and account data could not be checked"
                      : "Saved CWL signups could not be checked",
                    detail: accountError
                      ? "You cannot see saved signups or linked accounts until this check works."
                      : "You cannot change signups or saved accounts until this check works.",
                    technicalDetail: [dataError, accountError]
                      .filter(Boolean)
                      .join(" · "),
                    action: {
                      label: "Retry CWL data",
                      onClick: retrySignupRead,
                      disabled: loadingData || pending,
                    },
                  },
                ]
              : !activeCompletion && accountError
                ? [
                    {
                      title: "Linked accounts are unavailable",
                      detail:
                        "You cannot select accounts or change pools until the dashboard checks your links.",
                      technicalDetail: accountError,
                      action: {
                        label: "Retry CWL data",
                        onClick: retrySignupRead,
                        disabled: loadingData || pending,
                      },
                    },
                  ]
                : []),
          ]}
        />
      )}
      {seasonsLoading && <p role="status">Loading seasons…</p>}
      {!seasonId && !seasonsLoading && !seasonError && (
        <div className="card empty">
          <p>Staff will make the next CWL season available here.</p>
        </div>
      )}
      {season && (
        <>
          {!activeCompletion && loadingData && signupPanel === "register" && (
            <p role="status">Loading linked accounts…</p>
          )}
          <MemberSeasonLine
            season={season}
            hideClosedStatus={
              signupPanel === "register" && !memberSignupsOpen(season)
            }
          />
          {activeCompletion ? (
            <section
              className="completion-card card"
              aria-labelledby="completion-title"
            >
              <div className="completion-mark" aria-hidden="true">
                ✓
              </div>
              <h2
                id="completion-title"
                ref={completionHeadingRef}
                tabIndex={-1}
              >
                You are signed up
              </h2>
              <p>
                <strong>
                  {activeCompletion.accounts.length}{" "}
                  {activeCompletion.accounts.length === 1
                    ? "account is"
                    : "accounts are"}{" "}
                  signed up
                </strong>{" "}
                for {poolName(activeCompletion.pool)} in{" "}
                {activeCompletion.seasonLabel}.
              </p>
              <div className="completion-accounts">
                {activeCompletion.accounts.map((account) => (
                  <div key={account.tag}>
                    <strong>{account.name}</strong>
                    <small>{account.tag}</small>
                  </div>
                ))}
              </div>
              <p>
                Your accounts are signed up. Staff will assign them to clans.
                You can close this page, or sign up more accounts below.
              </p>
              {activeCompletion.refreshWarning && (
                <div className="notice error" role="alert">
                  Your signup is saved. The account list did not refresh. Check
                  your saved signups later.
                </div>
              )}
              <div className="completion-actions">
                <button
                  className="primary"
                  disabled={pending}
                  onClick={() => void showSavedSignups()}
                >
                  View my signups
                </button>
                <button
                  disabled={pending}
                  onClick={() => changeView("assignments")}
                >
                  My clan assignments
                </button>
                <button
                  disabled={pending}
                  onClick={() => {
                    setPoolRemoved([]);
                    setCompletion(null);
                    setSignupPanel("register");
                    setSignupStep(1);
                    setPool(null);
                    setReview(false);
                  }}
                >
                  Sign up more accounts
                </button>
              </div>
            </section>
          ) : (
            <>
              {signupPanel === "register" && !memberSignupsOpen(season) && (
                <section
                  data-tour-target="signup-closed"
                  className="signup-guide"
                  aria-label="Signup walkthrough"
                >
                  <h2>Signups closed</h2>
                  <p>
                    View your saved signups or check your CWL clan. To make a
                    change, ask staff for help.
                  </p>
                  <div className="signup-action-buttons">
                    <button onClick={() => changeSignupPanel("saved")}>
                      My signups
                    </button>
                    <button onClick={() => changeView("assignments")}>
                      My clan assignments
                    </button>
                  </div>
                </section>
              )}
              {signupPanel === "register" && memberSignupsOpen(season) && (
                <div className="signup-flow">
                  {accountsReady &&
                    !loadingData &&
                    !accountError &&
                    accounts.length === 0 && (
                      <section
                        className="card"
                        data-tour-target="signup-missing"
                      >
                        <h2>Link an account</h2>
                        <AccountLinkHelp
                          busy={loadingData || pending}
                          onRefresh={() => void loadSignup()}
                        />
                      </section>
                    )}
                  <SignupWalkthrough
                    stage={review ? 3 : signupStep}
                    pool={pool}
                    selectedCount={selected.length}
                    busy={pending}
                    canReview={
                      !!pool &&
                      selected.length > 0 &&
                      !loadingData &&
                      !dataError &&
                      !accountError
                    }
                    headingRef={stepHeadingRef}
                    onNavigate={(stage) => {
                      if (pending || (stage > 1 && !pool)) return;
                      if (
                        stage === 3 &&
                        (!selected.length ||
                          loadingData ||
                          dataError ||
                          accountError)
                      )
                        return;
                      setReturnToReview(review && stage === 1);
                      setReview(stage === 3);
                      setSignupStep(stage === 1 ? 1 : 2);
                    }}
                  />
                  {poolRemoved.length > 0 && (
                    <p className="notice" role="status">
                      No longer eligible for this pool: {poolRemoved.join(", ")}
                      . These accounts were removed from this unsaved selection.
                    </p>
                  )}
                  {signupStep === 1 && !review && (
                    <div className="pool-choice">
                      <div className="pool-choice-grid">
                        <button
                          className={pool === "main" ? "active" : ""}
                          aria-pressed={pool === "main"}
                          disabled={pending}
                          onClick={() => choosePool("main")}
                        >
                          <span className="pool-choice-symbol">◆</span>
                          <strong>Main CWL</strong>
                          <small>
                            Main: play at full strength. No hero upgrades.
                          </small>
                          <span className="pool-next">Select Main CWL →</span>
                        </button>
                        <button
                          data-tour-target="signup-pool"
                          className={pool === "lazy" ? "active" : ""}
                          aria-pressed={pool === "lazy"}
                          disabled={pending}
                          onClick={() => choosePool("lazy")}
                        >
                          <span className="pool-choice-symbol">◇</span>
                          <strong>Lazy CWL</strong>
                          <small>
                            Lazy: relaxed CWL. You can upgrade during the event.
                          </small>
                          <small className="fwa-cwl-note">
                            If you’re in FWA… it’s Lazy Way or No Way!!!
                          </small>
                          <span className="pool-next">Select Lazy CWL →</span>
                        </button>
                      </div>
                      <p className="small">
                        You can use different accounts for Main and Lazy CWL.
                      </p>
                    </div>
                  )}
                  {pool && signupStep === 2 && !review && (
                    <>
                      <CwlPoolTabs
                        value={pool}
                        onChange={choosePool}
                        disabled={pending || loadingData}
                      />
                      <div className="section-heading">
                        <div>
                          <h2 ref={selectionHeadingRef} tabIndex={-1}>
                            Select linked accounts
                          </h2>
                          <p>
                            {pool === "lazy"
                              ? "Linked accounts from any clan can join Lazy CWL. Each account can join one CWL pool per season."
                              : "Main CWL signup is separate from Lazy CWL. Each account can join one pool per season."}
                          </p>
                        </div>
                        <div className="count-pill">
                          {selected.length} selected
                        </div>
                      </div>

                      {!accountError && accounts.length > 0 && (
                        <>
                          {visibleAccounts.length > 0 && (
                            <>
                              <div className="selection-bar">
                                <label className="check-label">
                                  <input
                                    type="checkbox"
                                    checked={
                                      available.length > 0 &&
                                      available.every((account) =>
                                        Object.hasOwn(draft, account.tag),
                                      )
                                    }
                                    onChange={(event) => {
                                      if (!pool) return;
                                      if (event.target.checked)
                                        setDraft({
                                          ...draft,
                                          ...Object.fromEntries(
                                            available.map((account) => [
                                              account.tag,
                                              draft[account.tag] ?? false,
                                            ]),
                                          ),
                                        });
                                      else {
                                        const next = { ...draft };
                                        for (const account of available)
                                          delete next[account.tag];
                                        setDraft(next);
                                      }
                                    }}
                                    disabled={
                                      !memberSignupsOpen(season) ||
                                      !available.length ||
                                      pending ||
                                      loadingData ||
                                      !!dataError ||
                                      !!accountError
                                    }
                                  />
                                  Select all matching accounts (
                                  {available.length})
                                </label>
                                <button
                                  onClick={() => void loadSignup()}
                                  disabled={loadingData || pending}
                                >
                                  Refresh accounts
                                </button>
                              </div>
                              <label className="signup-account-search">
                                Find a player or clan
                                <input
                                  type="search"
                                  value={signupSearch}
                                  onChange={(event) =>
                                    setSignupSearch(event.target.value)
                                  }
                                  placeholder="Find a player or clan"
                                />
                              </label>
                            </>
                          )}
                          {visibleAccounts.length > 0 &&
                            matchingAccounts.length === 0 && (
                              <div className="card empty">
                                <p>No accounts match your search.</p>
                                <button onClick={() => setSignupSearch("")}>
                                  Clear search
                                </button>
                              </div>
                            )}
                          {visibleAccounts.length === 0 && (
                            <div className="card empty">
                              <h3>All your linked accounts are signed up.</h3>
                              <p>
                                To change or withdraw a signup, go to My
                                signups.
                              </p>
                              <button
                                disabled={pending}
                                onClick={() => changeSignupPanel("saved")}
                              >
                                My signups
                              </button>
                            </div>
                          )}
                          <details className="hub-help">
                            <summary data-tour-target="signup-missing">
                              Link an account
                            </summary>
                            <AccountLinkHelp
                              busy={loadingData || pending}
                              onRefresh={() => void loadSignup()}
                            />
                          </details>
                          <div className="account-list">
                            {pageAccounts.map((account, index) => {
                              const chosen =
                                Object.hasOwn(draft, account.tag) &&
                                !(
                                  pool === "main" &&
                                  account.current_clan_type === "FWA"
                                );
                              return (
                                <article
                                  data-tour-target={
                                    index === 0 ? "signup-account" : undefined
                                  }
                                  className={`account-card ${chosen ? "chosen" : ""}`}
                                  key={account.tag}
                                >
                                  <div className="account-top">
                                    <label className="account-select">
                                      <input
                                        type="checkbox"
                                        checked={chosen}
                                        disabled={
                                          !memberSignupsOpen(season) ||
                                          pending ||
                                          loadingData ||
                                          !!dataError ||
                                          !!accountError
                                        }
                                        onChange={(event) => {
                                          if (!pool) return;
                                          if (
                                            event.target.checked &&
                                            pool === "main" &&
                                            account.current_clan_type === "FWA"
                                          ) {
                                            setFwaBlocked(true);
                                            return;
                                          }
                                          const next = { ...draft };
                                          if (event.target.checked)
                                            next[account.tag] = false;
                                          else delete next[account.tag];
                                          setDraft(next);
                                        }}
                                      />
                                      <span>
                                        <strong className="signed-up-name">
                                          <TownHallIcon
                                            level={account.town_hall}
                                          />
                                          <span>{account.name}</span>
                                        </strong>
                                        <small>{account.tag}</small>
                                      </span>
                                    </label>
                                  </div>
                                  <div className="account-meta">
                                    <span>
                                      Current clan{" "}
                                      <strong>
                                        {account.current_clan_name || "None"}
                                        {account.current_clan_tag
                                          ? ` · ${account.current_clan_tag}`
                                          : ""}
                                      </strong>
                                    </span>
                                  </div>
                                  {pool === "main" &&
                                    account.current_clan_type === "FWA" && (
                                      <p className="inline-reason">
                                        FWA account · Lazy CWL only. Select Lazy
                                        CWL above to sign up this account.
                                      </p>
                                    )}
                                </article>
                              );
                            })}
                          </div>
                          {lastSignupPage > 0 && (
                            <nav
                              className="hub-pagination"
                              aria-label="Signup account pages"
                            >
                              <button
                                disabled={currentSignupPage === 0}
                                onClick={() =>
                                  setSignupPage(currentSignupPage - 1)
                                }
                              >
                                Previous accounts
                              </button>
                              <span>
                                Page {currentSignupPage + 1} of{" "}
                                {lastSignupPage + 1}
                              </span>
                              <button
                                disabled={currentSignupPage === lastSignupPage}
                                onClick={() =>
                                  setSignupPage(currentSignupPage + 1)
                                }
                              >
                                Next accounts
                              </button>
                            </nav>
                          )}
                          {memberSignupsOpen(season) &&
                            visibleAccounts.length > 0 && (
                              <div className="submit-bar">
                                <div>
                                  <strong>
                                    {selected.length}{" "}
                                    {selected.length === 1
                                      ? "account"
                                      : "accounts"}{" "}
                                    selected
                                  </strong>
                                  <small>
                                    Selections across all pages · Not saved yet.
                                  </small>
                                </div>
                                <div className="signup-action-buttons">
                                  <button
                                    disabled={pending}
                                    onClick={() => setSignupStep(1)}
                                  >
                                    ← Back
                                  </button>
                                  <button
                                    className="primary"
                                    disabled={
                                      !selected.length ||
                                      pending ||
                                      loadingData ||
                                      !!dataError ||
                                      !!accountError
                                    }
                                    onClick={() => setReview(true)}
                                  >
                                    Continue →
                                  </button>
                                </div>
                              </div>
                            )}
                        </>
                      )}
                    </>
                  )}
                  {signupStep === 2 &&
                    !review &&
                    (!accounts.length ||
                      accountError ||
                      !memberSignupsOpen(season)) && (
                      <button
                        disabled={pending}
                        onClick={() => setSignupStep(1)}
                      >
                        ← Back to CWL choice
                      </button>
                    )}
                  {review && pool && (
                    <section
                      data-tour-target="signup-review"
                      className="signup-review card"
                      aria-label="Review selected accounts"
                    >
                      {notice?.kind === "error" && (
                        <div className="notice error" role="alert">
                          {notice.text}
                        </div>
                      )}
                      <SignupReviewHeading
                        poolLabel={poolName(pool)}
                        count={selected.length}
                        busy={pending}
                        onChange={changeReviewStep}
                      />
                      <div className="review-list">
                        {selected.map((item) => {
                          const account = accounts.find(
                            (candidate) => candidate.tag === item.tag,
                          )!;
                          return (
                            <div className="review-row" key={item.tag}>
                              <div>
                                <strong className="signed-up-name">
                                  <TownHallIcon level={account.town_hall} />
                                  <span>{account.name}</span>
                                </strong>
                                <small>
                                  {account.tag} · TH {account.town_hall ?? "—"}{" "}
                                  ·{" "}
                                  {account.current_clan_name ||
                                    "No current clan"}
                                </small>
                              </div>
                              {account.current_clan_type === "FWA" &&
                                pool === "main" && (
                                  <span className="transfer-review">
                                    FWA account · Lazy CWL only.
                                  </span>
                                )}
                            </div>
                          );
                        })}
                      </div>
                      <div className="signup-actions submit-bar">
                        <button
                          disabled={pending}
                          onClick={() => setReview(false)}
                        >
                          ← Back
                        </button>
                        <button
                          data-tour-target="signup-confirm"
                          className="primary"
                          disabled={
                            !selected.length ||
                            pending ||
                            loadingData ||
                            !memberSignupsOpen(season) ||
                            !!dataError ||
                            !!accountError
                          }
                          onClick={submit}
                        >
                          {pending
                            ? "Saving…"
                            : `Sign up ${selected.length} ${selected.length === 1 ? "account" : "accounts"}`}
                        </button>
                      </div>
                    </section>
                  )}
                </div>
              )}
              {signupPanel === "saved" && (
                <section className="registered">
                  {!savedSignupsLoaded && !dataError ? (
                    <p role="status">Loading saved signups…</p>
                  ) : dataError ? null : (
                    <>
                      {loadingData && !existing.length && (
                        <p role="status">Checking linked accounts…</p>
                      )}
                      {existing.length > 0 && (
                        <SavedSignupStatus
                          signups={existing}
                          accounts={
                            loadingData || accountError ? null : accounts
                          }
                          accountsLoading={loadingData}
                          accountsUnavailable={!!accountError}
                          season={season}
                          onRemaining={() =>
                            changeSignupPanel("register", () => {
                              setSignupStep(1);
                              setPool(null);
                            })
                          }
                          onAssignments={() => changeView("assignments")}
                        />
                      )}
                      <SavedSignups
                        key={seasonId}
                        signups={existing}
                        accounts={accounts}
                        editable={memberSignupsOpen(season)}
                        busy={pending || loadingData}
                        canMove={!loadingData && !accountError}
                        headingRef={registeredHeadingRef}
                        onDirty={setSavedSignupDirty}
                        onSave={saveSavedSignups}
                        onWithdraw={(rows) => void withdraw(rows)}
                        onRefreshAccounts={retrySignupRead}
                      />
                      {!existing.length && (
                        <div className="card empty">
                          <p>No signed-up accounts for this season.</p>
                          {memberSignupsOpen(season) && (
                            <button
                              onClick={() =>
                                changeSignupPanel("register", () =>
                                  setSignupStep(1),
                                )
                              }
                            >
                              Select accounts
                            </button>
                          )}
                        </div>
                      )}
                      <button
                        disabled={pending || loadingData}
                        onClick={retrySignupRead}
                      >
                        Refresh saved signups
                      </button>
                    </>
                  )}
                </section>
              )}
            </>
          )}
        </>
      )}
    </>
  );
}
