// @vitest-environment happy-dom
import { afterEach, expect, it, vi } from "vitest";
import { api, apiUpload, reportBrowserIssue } from "../api";
import { writeSnapshot } from "../snapshotCache";
import { saveTodoPreferences } from "../todoPreferences";
import { setTourReadOnly } from "./session";

afterEach(() => {
  setTourReadOnly(false);
  vi.unstubAllGlobals();
});
it("blocks every write before fetch during practice, including direct confirmation and uploads", async () => {
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  setTourReadOnly(true);
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    await expect(api("/seasons/1/signups", method)).rejects.toThrow(
      "Practice — nothing saved.",
    );
  }
  await expect(
    apiUpload("/upload", new File([], "fixture.png")),
  ).rejects.toThrow("Practice — nothing saved.");
  await reportBrowserIssue("browser_error");
  expect(fetcher).not.toHaveBeenCalled();
});
it("permits reads during the tour and restores normal requests afterward", async () => {
  const fetcher = vi
    .fn()
    .mockResolvedValue(new Response("{}", { status: 200 }));
  vi.stubGlobal("fetch", fetcher);
  setTourReadOnly(true);
  await api("/seasons");
  expect(fetcher).toHaveBeenCalledOnce();
  setTourReadOnly(false);
  await api("/seasons/1/signups", "POST");
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("does not persist Tasks choices or display snapshots during practice", () => {
  const storage = { setItem: vi.fn() };
  setTourReadOnly(true);
  writeSnapshot("tour", {}, storage);
  saveTodoPreferences(
    "member",
    { tab: "war", selected: null, sort: "deadline" },
    storage,
  );
  expect(storage.setItem).not.toHaveBeenCalled();
  setTourReadOnly(false);
  writeSnapshot("tour", {}, storage);
  saveTodoPreferences(
    "member",
    { tab: "war", selected: null, sort: "deadline" },
    storage,
  );
  expect(storage.setItem).toHaveBeenCalledTimes(2);
});
