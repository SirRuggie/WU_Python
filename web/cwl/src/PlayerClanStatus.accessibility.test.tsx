// @vitest-environment happy-dom
import { renderToStaticMarkup } from "react-dom/server";
import { expect, it } from "vitest";
import PlayerClanStatus, { playerClanStatus } from "./PlayerClanStatus";

it("gives the spoken Now in clan description one named, accessible note", () => {
  const status = playerClanStatus(
    "#HOME",
    "Home",
    {
      current_clan_tag: "#OTHER",
      current_clan_name: "Other clan",
      current_clan_checked_at: "2026-10-28T12:00:00Z",
    },
    Date.parse("2026-10-28T12:04:00Z"),
  );
  const host = document.createElement("div");
  host.innerHTML = renderToStaticMarkup(<PlayerClanStatus status={status} />);
  const namedNotes = [...host.querySelectorAll('[role="note"]')].filter(
    (note) => note.getAttribute("aria-label")?.includes("Now in Other clan"),
  );
  expect(namedNotes).toHaveLength(1);
  expect(namedNotes[0].getAttribute("aria-label")).toBe(status.description);
  expect(namedNotes[0].classList.contains("sr-only")).toBe(true);
  expect(namedNotes[0].textContent).toBe("");
  expect(
    host.querySelector('.player-location-pin[aria-hidden="true"]'),
  ).not.toBeNull();
  expect(
    host.querySelector('.player-location-pin[aria-label="Now in"]'),
  ).toBeNull();
});
