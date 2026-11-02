// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it } from "vitest";
import DeclarationExtras from "./DeclarationExtras";
let root: ReturnType<typeof createRoot>, host: HTMLDivElement;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const base = {
  tag: "#PYY",
  name: "Fixture",
  capacity: 15,
  status: "current" as const,
  checked_at: new Date().toISOString(),
  count: 0,
  extras: [],
};
it("distinguishes empty, failed and never-checked observations", async () => {
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={base}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("0 not on roster");
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{ ...base, status: "unavailable", count: null, extras: null }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("Couldn't check");
  expect(host.textContent).not.toContain("0 not on roster");
  expect(host.textContent).toContain("Last checked");
  await act(async () =>
    root.render(<DeclarationExtras loading={true} error="" now={Date.now()} />),
  );
  expect(host.textContent).toBe("Checking clan members…");
});
it("lists account identity and context without a send action or external HTML", async () => {
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{
          ...base,
          count: 1,
          extras: [
            {
              tag: "#QYY",
              name: "<img src=x> @everyone",
              town_hall: 16,
              context: "Assigned to Other clan",
              assigned_clan_tag: "#RYY",
            },
          ],
        }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("⚠ 1 not on roster");
  expect(host.textContent).toContain("TH 16");
  expect(host.textContent).toContain("Assigned to Other clan");
  expect(host.querySelector("img")).toBeNull();
  expect(host.querySelector("button")).toBeNull();
});

it("a completed response missing this clan is terminal unavailable", async () => {
  await act(async () =>
    root.render(
      <DeclarationExtras loading={false} error="" now={Date.now()} />,
    ),
  );
  expect(host.textContent).toContain("Couldn't check");
  expect(host.textContent).not.toContain("Checking");
  expect(host.textContent).not.toContain("0 not on roster");
});
it("separates a neutral draft move from intruders without changing account counts", async () => {
  const person = {
    tag: "#P",
    name: "Moved account",
    town_hall: 16,
    context: "Assigned to Fixture",
    assigned_clan_tag: "#PYY",
    not_published_yet: true,
  };
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{
          ...base,
          count: 1,
          extras: [
            {
              ...person,
              tag: "#Q",
              name: "Real intruder",
              not_published_yet: undefined,
              context: "Assigned to Other",
            },
          ],
          unpublished: [person],
          unpublished_count: 1,
        }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("1 not on roster · 1 not published yet");
  expect(host.textContent).toContain("Moved here · not published yet");
  expect(host.querySelector(".is-unpublished")?.textContent).not.toContain(
    "Assigned to Fixture",
  );
  expect(host.querySelectorAll(".is-unpublished")).toHaveLength(1);
  expect(host.querySelectorAll(".declaration-member-account")).toHaveLength(2);
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{ ...base, unpublished: [person], unpublished_count: 1 }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.querySelector("details")?.classList.contains("is-neutral")).toBe(
    true,
  );
  expect(host.textContent).toContain("0 not on roster · 1 not published yet");
});
it("does not turn incomplete unpublished counts into zero", async () => {
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{ ...base, unpublished_count: null }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.textContent).toContain("Couldn't check");
  expect(host.textContent).not.toContain("0 not on roster");
});
it("uses one identity and DM across low TH, intruder and unpublished categories", async () => {
  const uid = "123456789012345678";
  const member = (tag: string, th: number) => ({
    tag,
    name: tag,
    town_hall: th,
    context: "Assigned to Fixture",
    assigned_clan_tag: "#PYY",
    discord_id: uid,
    discord_profile: { id: uid, display_name: "One person" },
  });
  const low = member("#LOW", 9),
    intruder = member("#INTRUDER", 16),
    pending = { ...member("#MOVED", 16), not_published_yet: true };
  await act(async () =>
    root.render(
      <DeclarationExtras
        row={{
          ...base,
          count: 1,
          extras: [intruder],
          low_th: [low],
          fillers: [low],
          unpublished: [pending],
          unpublished_count: 1,
        }}
        loading={false}
        error=""
        now={Date.now()}
      />,
    ),
  );
  expect(host.querySelectorAll(".discord-identity-compact")).toHaveLength(1);
  expect(host.querySelectorAll("a.discord-contact")).toHaveLength(1);
  expect(host.querySelectorAll(".declaration-member-account")).toHaveLength(3);
  expect(host.textContent).toContain(
    "1 not on roster · 1 not published yet · 1 low TH in clan",
  );
});
