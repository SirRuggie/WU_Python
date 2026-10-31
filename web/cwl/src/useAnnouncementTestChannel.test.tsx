// @vitest-environment happy-dom
import { act } from "react";
import { createRoot } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import useAnnouncementTestChannel from "./useAnnouncementTestChannel";
const { api } = vi.hoisted(() => ({ api: vi.fn() }));
vi.mock("./api", () => ({ api }));
let host: HTMLDivElement, root: ReturnType<typeof createRoot>;
let state: ReturnType<typeof useAnnouncementTestChannel>;
function Fixture({ allowed = true }: { allowed?: boolean }) {
  state = useAnnouncementTestChannel(allowed);
  return null;
}
beforeEach(async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  api.mockReset();
  api.mockImplementation(async (_path, method, body) => ({
    channel_id: method === "PUT" ? body.channel_id : "111111111111111111",
    channel_name: "test",
    revision: method === "PUT" ? 8 : 7,
  }));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  await act(async () => root.render(<Fixture />));
});
afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});
it("preselects the shared default, but a per-send override never saves without the checkbox", async () => {
  expect(state.channel).toBe("111111111111111111");
  await act(async () => state.setChannel("222222222222222222"));
  await act(async () => state.saveDefault());
  expect(api.mock.calls.filter((call) => call[1] === "PUT")).toHaveLength(0);
  expect(state.channel).toBe("222222222222222222");
});
it("saves only an explicit default choice with the loaded revision", async () => {
  await act(async () => {
    state.setChannel("222222222222222222");
    state.setMakeDefault(true);
  });
  await act(async () => state.saveDefault());
  expect(api).toHaveBeenLastCalledWith(
    "/manage/announcement-test-channel",
    "PUT",
    { channel_id: "222222222222222222", expected_revision: 7 },
  );
  expect(state.makeDefault).toBe(false);
});
it("retains the override on a conflict and reloads its revision without overwriting the selection", async () => {
  await act(async () => {
    state.setChannel("222222222222222222");
    state.setMakeDefault(true);
  });
  api.mockRejectedValueOnce(new Error("409 Test channel changed"));
  await act(async () => { await expect(state.saveDefault()).rejects.toThrow("409"); });
  expect(state.error).toContain("409");
  expect(state.channel).toBe("222222222222222222");
  expect(state.makeDefault).toBe(true);
  await act(async () => state.reload());
  expect(state.error).toBe("");
  expect(state.channel).toBe("222222222222222222");
});
it("clears an override on permission loss and restores the default when permission returns", async () => {
  await act(async () => state.setChannel("222222222222222222"));
  await act(async () => root.render(<Fixture allowed={false} />));
  expect(state.channel).toBe("");
  await act(async () => root.render(<Fixture allowed />));
  expect(state.channel).toBe("111111111111111111");
});
