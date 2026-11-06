import { Fragment, type ButtonHTMLAttributes, type ReactNode } from "react";
import TownHallIcon from "./TownHallIcon";
import "./rosterUi/tokens.css";
import "./PlayerCard.css";
import "./AccountCard.css";

type Props = {
  variant?: "participation";
  select?: ReactNode;
  thLevel: number | null | undefined;
  name: ReactNode;
  values?: ReactNode;
  action?: ReactNode;
  meta: ReactNode[];
  status: { tone: "good" | "bad" | "neutral"; content: ReactNode };
  flags?: ReactNode[];
  className?: string;
  children?: ReactNode;
};
const parts = (items: ReactNode[]) =>
  items.filter(
    (part) =>
      part !== null && part !== undefined && part !== false && part !== "",
  );
const joined = (items: ReactNode[]) =>
  parts(items).map((part, index) => (
    <Fragment key={index}>
      {index > 0 ? " · " : ""}
      {part}
    </Fragment>
  ));

type StructuralProps = {
  variant: "structural";
  className: string;
  beforeBody?: ReactNode;
  body?: Pick<
    ButtonHTMLAttributes<HTMLButtonElement>,
    "onClick" | "disabled" | "aria-label" | "aria-describedby"
  > & { type: "button"; className: string };
  top: {
    element: "span" | "div";
    className: string;
    name: ReactNode;
    aside?: ReactNode;
  };
  rows: ReactNode;
  afterBody?: ReactNode;
};

export default function AccountCard(props: Props | StructuralProps) {
  if (props.variant === "structural") {
    const Top = props.top.element;
    const content = (
      <>
        <Top className={props.top.className}>
          {props.top.name}
          {props.top.aside}
        </Top>
        {props.rows}
      </>
    );
    return (
      <article className={props.className}>
        {props.beforeBody}
        {props.body ? <button {...props.body}>{content}</button> : content}
        {props.afterBody}
      </article>
    );
  }
  const {
    select,
    thLevel,
    name,
    values,
    action,
    meta,
    status,
    flags = [],
    className = "",
    children,
  } = props;
  const visibleFlags = parts(flags);
  const hasValues = parts([values]).length > 0;
  const toneClass =
    status.tone === "good"
      ? " is-assigned"
      : status.tone === "bad"
        ? " compare-account-missing"
        : "";
  return (
    <article className={`shared-account-card ${className}`}>
      <div className="roster-ui">
        <div className={`player-card${toneClass}`}>
          <div className="account-card-layout player-card-body">
            {select && <div className="account-card-select">{select}</div>}
            <div
              className={`account-card-content${hasValues ? " has-values" : ""}`}
            >
              <div className="player-card-top">
                <strong className="player-card-name account-card-name">
                  <span className="player-card-inline-th" aria-hidden="true">
                    <TownHallIcon level={thLevel} />
                  </span>
                  <span className="player-card-name-text">{name}</span>
                </strong>
              </div>
              <div className="player-card-meta account-card-meta">
                {joined(meta)}
              </div>
              <div className="roster-player-placement account-card-status-row">
                {hasValues && (
                  <div className="account-card-values">{values}</div>
                )}
                {hasValues && (
                  <span className="account-card-value-separator"> · </span>
                )}
                <span className="player-clan-status account-card-status">
                  <span
                    className={`roster-player-placement${status.tone === "good" ? " is-in-clan" : status.tone === "neutral" ? " is-unassigned" : ""}`}
                  >
                    {status.tone === "bad" ? (
                      <span className="player-current-clan is-elsewhere">
                        {status.content}
                      </span>
                    ) : (
                      <strong>{status.content}</strong>
                    )}
                  </span>
                </span>
              </div>
              {visibleFlags.length > 0 && (
                <div className="player-card-meta account-card-flags">
                  {joined(visibleFlags)}
                </div>
              )}
              {action && <div className="account-card-action">{action}</div>}
            </div>
          </div>
        </div>
      </div>
      {children}
    </article>
  );
}
