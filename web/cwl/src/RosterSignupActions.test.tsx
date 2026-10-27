import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import type { RosterAccount, RosterClan } from "./roster";
import { RosterSignupReview } from "./RosterSignupActions";

const account = (
  tag: string,
  pool: "main" | "lazy",
  host: string | null,
  name = tag,
) =>
  ({
    tag,
    pool,
    assigned_clan_tag: host,
    player_name: name,
  }) as RosterAccount;
const clans = [{ tag: "#HOST", name: "W. U. Lazy.125" }] as RosterClan[];
const render = (
  action: "main" | "lazy" | "remove",
  accounts: RosterAccount[],
) =>
  renderToStaticMarkup(
    <RosterSignupReview
      accounts={accounts}
      clans={clans}
      action={action}
      busy={false}
      onCancel={() => {}}
      onConfirm={() => {}}
    />,
  );

describe("reviewing signup changes", () => {
  it("counts only accounts changing pool and names a placement that will be cleared", () => {
    const html = render("lazy", [
      account("#ONE", "main", "#HOST"),
      account("#TWO", "lazy", null),
    ]);
    expect(html).toContain("1 of 2 selected accounts will change");
    expect(html).toContain("1 working placement will be cleared");
    expect(html).toContain("Assigned to W. U. Lazy.125");
  });

  it("shows that removal affects every account and escapes external player names", () => {
    const html = render("remove", [
      account("#ONE", "main", null, "<script>alert(1)</script>"),
    ]);
    expect(html).toContain("1 of 1 selected account will change");
    expect(html).toContain("Confirm remove signups");
    expect(html).toContain("&lt;script&gt;");
    expect(html).not.toContain("<script>");
  });
});

it("lists hidden and locked accounts and explains immediate pool visibility", () => {
  const locked = { ...account("#LOCK", "main", "#HOST"), kept: true };
  const html = renderToStaticMarkup(
    <RosterSignupReview
      accounts={[locked]}
      clans={clans}
      action="lazy"
      hiddenTags={[locked.tag]}
      busy={false}
      onCancel={() => {}}
      onConfirm={() => {}}
    />,
  );
  expect(html).toContain("Locked — affected");
  expect(html).toContain("Hidden by filters");
  expect(html).toContain("placement and lock are cleared");
  expect(html).toContain("visible to members immediately");
});
