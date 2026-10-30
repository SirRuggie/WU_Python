import type { CSSProperties, ReactNode } from "react";
import "./ModerationPreviewCard.css";

type Json = Record<string, unknown>;
const record = (value: unknown): value is Json =>
  !!value && typeof value === "object" && !Array.isArray(value);
const children = (value: unknown): unknown[] =>
  Array.isArray(value) ? value : [];
const text = (value: unknown): string =>
  typeof value === "string" ? value : "";

function discordText(value: string, names: Record<string, string>): ReactNode {
  return value.split("\n").map((line, lineIndex) => {
    const heading = line.startsWith("### ");
    const content = heading ? line.slice(4) : line;
    const parts = content.split(
      /(\*\*[^*]+\*\*|<@!?\d+>|<t:\d+:[fFR]>|ID \d+)/g,
    );
    const rendered = parts.map((part, index) => {
      if (part.startsWith("**") && part.endsWith("**")) {
        return <strong key={index}>{part.slice(2, -2)}</strong>;
      }
      const mention = /^<@!?(\d+)>$/.exec(part);
      if (mention) {
        return (
          <span
            key={index}
            className="moderation-preview-mention"
            title={mention[1]}
          >
            {names[mention[1]] || "Unknown member"}
          </span>
        );
      }
      const identity = /^ID (\d+)$/.exec(part);
      if (identity)
        return (
          <span key={index} title={identity[1]}>
            Member
          </span>
        );
      const stamp = /^<t:(\d+):([fFR])>$/.exec(part);
      if (stamp) {
        const date = new Date(Number(stamp[1]) * 1000);
        if (!Number.isNaN(date.getTime())) {
          const label =
            stamp[2] === "R"
              ? new Intl.RelativeTimeFormat(undefined, {
                  numeric: "auto",
                }).format(
                  Math.round((date.getTime() - Date.now()) / 86400000),
                  "day",
                )
              : date.toLocaleString(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                });
          return (
            <time key={index} dateTime={date.toISOString()}>
              {label}
            </time>
          );
        }
      }
      return part;
    });
    return (
      <span
        key={lineIndex}
        className={heading ? "moderation-preview-title" : undefined}
      >
        {rendered}
        {lineIndex < value.split("\n").length - 1 && <br />}
      </span>
    );
  });
}

function profileButton(component: Json, key: number): ReactNode {
  const url = text(component.url);
  const safe = /^https:\/\/discord\.com\/users\/\d+$/.test(url);
  return safe ? (
    <a key={key} href={url} target="_blank" rel="noreferrer noopener">
      {text(component.label) || "View profile ↗"}
    </a>
  ) : (
    <span key={key}>{text(component.label)}</span>
  );
}

function renderComponent(
  value: unknown,
  key: number,
  names: Record<string, string>,
): ReactNode {
  if (!record(value)) return null;
  switch (value.type) {
    case 17: {
      const accent = Number(value.accent_color);
      const style = Number.isFinite(accent)
        ? ({
            "--moderation-accent": `#${accent.toString(16).padStart(6, "0")}`,
          } as CSSProperties)
        : undefined;
      return (
        <div className="moderation-preview-container" style={style} key={key}>
          {children(value.components).map((item, index) =>
            renderComponent(item, index, names),
          )}
        </div>
      );
    }
    case 9:
      return (
        <div className="moderation-preview-section" key={key}>
          <div>
            {children(value.components).map((item, index) =>
              renderComponent(item, index, names),
            )}
          </div>
          <span
            className="moderation-preview-avatar"
            aria-label="Sample member avatar"
          >
            👤
          </span>
        </div>
      );
    case 10:
      return (
        <p className="moderation-preview-text" key={key}>
          {discordText(text(value.content), names)}
        </p>
      );
    case 14:
      return <hr key={key} />;
    case 1:
      return (
        <div className="moderation-preview-actions" key={key}>
          {children(value.components).map((item, index) =>
            renderComponent(item, index, names),
          )}
        </div>
      );
    case 2:
      return profileButton(value, key);
    default:
      return null;
  }
}

function renderForumEmbed(
  payload: Json,
  names: Record<string, string>,
): ReactNode {
  const embed = children(payload.embeds).find(record);
  if (!embed) return null;
  const accent = Number(embed.color);
  const style = Number.isFinite(accent)
    ? ({
        "--moderation-accent": `#${accent.toString(16).padStart(6, "0")}`,
      } as CSSProperties)
    : undefined;
  return (
    <div className="moderation-preview-container" style={style}>
      <strong className="moderation-preview-title">{text(embed.title)}</strong>
      {typeof embed.description === "string" && (
        <p>{discordText(embed.description, names)}</p>
      )}
      {children(embed.fields)
        .filter(record)
        .map((field, index) => (
          <p key={index}>
            <strong>{text(field.name)}</strong>
            <br />
            {discordText(text(field.value), names)}
          </p>
        ))}
      {record(embed.footer) && (
        <small>{discordText(text(embed.footer.text), names)}</small>
      )}
      <div className="moderation-preview-actions">
        {children(payload.components).map((item, index) =>
          renderComponent(item, index, names),
        )}
      </div>
    </div>
  );
}

export default function ModerationPreviewCard({
  payload,
  forum = false,
  names = {},
}: {
  payload: unknown;
  forum?: boolean;
  names?: Record<string, string>;
}) {
  if (!record(payload)) return <p>Preview unavailable.</p>;
  const display = forum
    ? renderForumEmbed(payload, names)
    : children(payload.components).map((item, index) =>
        renderComponent(item, index, names),
      );
  return (
    <div
      className="moderation-preview-card"
      aria-label={forum ? "Forum starter preview" : "Log card preview"}
    >
      {display}
      {forum && <small>Forum channels start a new post with this card.</small>}
    </div>
  );
}
