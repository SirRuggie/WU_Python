import { useEffect, useState } from "react";
import { api } from "./api";

export type HealthItem = {
  key: string;
  level: "warning" | "error";
  text: string;
};
type HealthResponse = {
  items?: HealthItem[];
  backlog?: number;
  last_sent_at?: string | null;
};

/** Read-only status line. A failed read renders nothing and never blocks the form. */
export default function ModerationHealth() {
  const [items, setItems] = useState<HealthItem[]>([]);

  useEffect(() => {
    let current = true;
    api<HealthResponse>("/manage/member-events/health")
      .then((result) => {
        if (current)
          setItems(
            Array.isArray(result?.items)
              ? result.items.filter((item) => typeof item?.text === "string")
              : [],
          );
      })
      .catch(() => {
        if (current) setItems([]);
      });
    return () => {
      current = false;
    };
  }, []);

  if (items.length === 0) return null;
  return (
    <ul className="moderation-health" aria-label="Log health">
      {items.map((item) => (
        <li key={item.key} className={`is-${item.level}`}>
          <span aria-hidden="true">{item.level === "error" ? "⛔" : "⚠️"}</span>
          {item.text}
        </li>
      ))}
    </ul>
  );
}
