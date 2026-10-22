import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import SignupMemberGroup from "./SignupMemberGroup";
import type { Signup } from "./api";
const accounts: Signup[] = [
  {
    tag: "#P2Y",
    user_id: "505227988229554179",
    pool: "lazy",
    prefer_crystal_1_or_lower: false,
    player_name: "<Sample>",
    town_hall: 18,
    has_staff_placement: true,
    assigned_clan_name: "Lazy Host",
    assigned_clan_tag: "#R2Y",
  },
];
function render(editable: boolean, rows: Signup[] = accounts, name = "Sample member") {
  return renderToStaticMarkup(
    <SignupMemberGroup
      accounts={rows}
      name={name}
      seasonId={1}
      revision={1}
      editable={editable}
      disabled={false}
      onActive={() => {}}
      onBusy={() => {}}
      onChanged={async () => {}}
    />,
  );
}
describe("compact signup groups", () => {
  it("shows exact placement and safe player text with a visible manage action", () => {
    const html = render(true);
    expect(html).toContain("Lazy Host");
    expect(html).toContain("&lt;Sample&gt;");
    expect(html).toContain("Edit signup</button>");
    expect(html).toContain("Message ↗");
    expect(html).not.toContain("Placed in working roster");
  });
  it("shows awaiting placement when there is no staff assignment", () => {
    const html = render(true, [{
      ...accounts[0],
      has_staff_placement: false,
      assigned_clan_name: null,
      assigned_clan_tag: null,
    }]);
    expect(html).toContain("Awaiting placement");
    expect(html).not.toContain("Assigned</small>");
    expect(html).not.toContain("Lazy Host");
  });
  it("falls back to the saved clan tag when an assigned clan name is unavailable", () => {
    const html = render(true, [{
      ...accounts[0],
      user_id: "",
      assigned_clan_name: null,
      assigned_clan_tag: "#OLD",
    }], "No Discord account");
    expect(html).toContain("#OLD");
    expect(html).not.toContain("Awaiting placement");
    expect(html).toContain("No Discord account");
    expect(html).not.toContain("Message ↗");
  });
  it("omits mutation controls when read only", () => {
    const html = render(false);
    expect(html).not.toContain('type="checkbox"');
    expect(html).not.toContain("Edit signup</button>");
    expect(html).toContain("Lazy Host");
  });
});
