import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import TodoActivityStatus, { TodoPrivateNote } from "./TodoActivityStatus";
import type { TodoRow, TodoView } from "./todo";
const unreadableRow = (tag: string, detail: string): TodoRow => ({
  tag,
  name: tag,
  town_hall: 16,
  clan_tag: "#CLAN",
  clan_name: "Hidden",
  used: null,
  total: null,
  remaining: null,
  starts_at: null,
  ends_at: null,
  state: "private",
  detail,
});
describe("Private war log note", () => {
  const ok: TodoView = {
    ok: true,
    rows: [],
    incomplete: "",
    note: "",
    notes: [],
    unavailable: "",
  };
  it("shows no top warning when the only gap is a private war log", () => {
    expect(
      renderToStaticMarkup(
        <TodoActivityStatus
          view={ok}
          hasRows
          unreadable={2}
          onAffected={() => {}}
        />,
      ),
    ).toBe("");
  });
  it("states the private war log as a neutral fact", () => {
    const one = renderToStaticMarkup(
      <TodoPrivateNote
        rows={[unreadableRow("#A", "private")]}
        onView={() => {}}
      />,
    );
    expect(one).toContain(
      "1 account is in a clan with a private war log. Check its attacks in-game.",
    );
    expect(one).toContain("View accounts");
    expect(one).not.toContain("could not be checked");
    const two = renderToStaticMarkup(
      <TodoPrivateNote
        rows={[unreadableRow("#A", "private"), unreadableRow("#B", "private")]}
        onView={() => {}}
      />,
    );
    expect(two).toContain(
      "2 accounts are in a clan with a private war log. Check their attacks in-game.",
    );
  });
  it("does not call a failed war read a private log", () => {
    const html = renderToStaticMarkup(
      <TodoPrivateNote
        rows={[unreadableRow("#A", "private"), unreadableRow("#B", "error")]}
        onView={() => {}}
      />,
    );
    expect(html).toContain("1 account is in a clan with a private war log.");
    expect(html).toContain("1 account could not be checked right now.");
  });
});
const partial: TodoView = {
  ok: true,
  rows: [],
  incomplete: "9 accounts failed; 33 accounts missing",
  note: "9 accounts failed; 33 accounts missing",
  notes: ["9 accounts failed", "33 accounts missing"],
  unavailable: "",
};
describe("Tasks failure presentation", () => {
  it("renders one notice and deduplicates the screenshot’s repeated warnings", () => {
    const html = renderToStaticMarkup(
      <TodoActivityStatus
        view={partial}
        hasRows={false}
        unreadable={9}
        onAffected={() => {}}
      />,
    );
    expect(html.match(/class="todo-warning"/g)).toHaveLength(1);
    expect(html.match(/9 accounts failed/g)).toHaveLength(1);
    expect(html.match(/33 accounts missing/g)).toHaveLength(1);
    expect(html).toMatch(/<details><summary\b[^>]*>Check details<\/summary>/);
    expect(html).toContain("Could not load this activity");
    expect(html).not.toContain("logs are private");
  });
  it("keeps partial results and loading distinct from a successful empty result", () => {
    expect(
      renderToStaticMarkup(
        <TodoActivityStatus
          view={partial}
          hasRows
          unreadable={0}
          onAffected={() => {}}
        />,
      ),
    ).toContain("Some tasks are missing");
    expect(
      renderToStaticMarkup(
        <TodoActivityStatus
          view={{ ...partial, loading: true }}
          hasRows={false}
          unreadable={0}
          onAffected={() => {}}
        />,
      ),
    ).toBe("");
    expect(
      renderToStaticMarkup(
        <TodoActivityStatus
          view={{ ...partial, incomplete: "", note: "", notes: [] }}
          hasRows={false}
          unreadable={0}
          onAffected={() => {}}
        />,
      ),
    ).toBe("");
  });
});
