import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SavedSignups from "./SavedSignups";
import type { Signup } from "./api";

function render(
  canMove: boolean,
  busy = false,
  signups: Signup[] = [
    { tag: "#P2Y", player_name: "Saved warrior", pool: "lazy" } as Signup,
  ],
) {
  return renderToStaticMarkup(
    <SavedSignups
      signups={signups}
      accounts={[]}
      editable
      busy={busy}
      canMove={canMove}
      headingRef={{ current: null }}
      onSave={async () => ({ saved: [], error: null })}
      onDirty={() => {}}
      onWithdraw={() => {}}
      onRefreshAccounts={() => {}}
    />,
  );
}

describe("saved signup account availability", () => {
  it("explains a missing link without hiding the saved signup", () => {
    const html = render(true);
    expect(html).toContain("Saved warrior");
    expect(html).toContain(
      "1 saved account is missing from the current linked-account list",
    );
    expect(html).toContain("Refresh accounts");
    expect(html).toContain("Link needs checking");
    expect(html).toContain("#P2Y");
    expect(html).toMatch(/disabled="">Change CWL pool/);
  });
  it("consolidates multiple absent accounts into one summary with disclosed names and tags", () => {
    const html = render(true, false, [
      { tag: "#P2Y", player_name: "Saved warrior", pool: "lazy" } as Signup,
      { tag: "#P3Z", player_name: "Second warrior", pool: "main" } as Signup,
    ]);
    expect(
      html.match(/missing from the current linked-account list/g),
    ).toHaveLength(1);
    expect(html).toContain("Saved warrior · #P2Y\nSecond warrior · #P3Z");
  });
  it("does not claim an account is unlinked when the provider is unavailable", () => {
    expect(render(false)).not.toContain(
      "missing from the current linked-account list",
    );
    expect(render(false)).not.toContain("Link needs checking");
  });
  it("keeps the saved record visible while links are still being checked", () => {
    const html = render(false, true);
    expect(html).toContain("Saved warrior");
    expect(html).not.toContain("missing from the current linked-account list");
    expect(html).not.toContain("Link needs checking");
    expect(html).toMatch(/disabled="">Withdraw signup/);
  });
});

it("shows the clan-change guidance once only while changes are allowed", () => {
  const signups = [
    { tag: "#P2Y", pool: "main", has_staff_placement: true },
    { tag: "#P3Z", pool: "lazy", has_staff_placement: true },
  ] as Signup[];
  const markup = (editable: boolean) =>
    renderToStaticMarkup(
      <SavedSignups
        signups={signups}
        accounts={[]}
        editable={editable}
        busy={false}
        canMove
        headingRef={{ current: null }}
        onSave={async () => ({ saved: [], error: null })}
        onDirty={() => {}}
        onWithdraw={() => {}}
      />,
    );
  expect(markup(true).match(/Changing pools or withdrawing/g)).toHaveLength(1);
  expect(markup(true)).not.toContain("working placement");
  expect(markup(false)).not.toContain("Changing pools or withdrawing");
});
