// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
vi.mock("../api", async (original) => ({
  ...(await original<object>()),
  api: vi.fn(),
}));
import { api } from "../api";
import RoleChangeReview from "./RoleChangeReview";
const ROLE = "333333333333333333",
  ids = ["111111111111111111", "222222222222222222"];
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(api).mockReset();
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
const response = () => ({
  token: "review",
  selected: [...ids],
  count: 2,
  role: { id: ROLE, name: "Officer", protected: false },
  operation: "remove" as const,
});
async function render(onConfirm = vi.fn().mockResolvedValue(true)) {
  await act(async () =>
    root.render(
      <RoleChangeReview
        ids={ids}
        operation="remove"
        roles={[{ id: ROLE, name: "Officer" }]}
        onCancel={() => {}}
        onConfirm={onConfirm}
        onDenied={() => {}}
      />,
    ),
  );
  const select = document.querySelector("select")!;
  await act(async () => {
    select.value = ROLE;
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  return onConfirm;
}
function button(label: string) {
  const found = [...document.querySelectorAll("button")].find(
    (b) => b.textContent === label,
  );
  expect(found).toBeTruthy();
  return found!;
}
it("names the exact hidden-inclusive count and requires a separate confirmation", async () => {
  vi.mocked(api).mockResolvedValue(response());
  const confirm = await render();
  await act(async () => {
    button("Review changes").click();
    button("Review changes").click();
  });
  expect(api).toHaveBeenCalledTimes(1);
  expect(vi.mocked(api).mock.calls[0][2]).toEqual({
    member_ids: ids,
    role_id: ROLE,
    operation: "remove",
  });
  expect(document.body.textContent).toContain("Remove Officer from 2 members");
  expect(confirm).not.toHaveBeenCalled();
  await act(async () => button("Remove role").click());
  expect(confirm).toHaveBeenCalledTimes(1);
  expect(confirm.mock.calls[0][0].selected).toEqual(ids);
});
it("rejects a count/IDs mismatch before any action confirmation", async () => {
  vi.mocked(api).mockResolvedValue({
    ...response(),
    count: 1,
    selected: [ids[0]],
  });
  const confirm = await render();
  await act(async () => button("Review changes").click());
  expect(document.querySelector("[role=alert]")?.textContent).toContain(
    "Review the selection again",
  );
  expect(confirm).not.toHaveBeenCalled();
});
it("shows protected access warning and never confirms automatically", async () => {
  vi.mocked(api).mockResolvedValue({
    ...response(),
    role: { id: ROLE, name: "Officer", protected: true },
  });
  const confirm = await render();
  await act(async () => button("Review changes").click());
  expect(document.body.textContent).toContain("This role gives extra access");
  expect(confirm).not.toHaveBeenCalled();
  await act(async () => button("Keep role").click());
  expect(confirm).not.toHaveBeenCalled();
});
