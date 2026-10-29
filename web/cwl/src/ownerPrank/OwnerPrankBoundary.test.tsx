// @vitest-environment happy-dom
import { Suspense, act, lazy } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import OwnerPrankBoundary from "./OwnerPrankBoundary";

it("silently releases the tour when the lazy prank chunk fails", async () => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });
  const host = document.createElement("div");
  document.body.append(host);
  const root = createRoot(host);
  const onFailure = vi.fn();
  const errorLog = vi.spyOn(console, "error").mockImplementation(() => {});
  const FailedChunk = lazy(() =>
    Promise.reject(new Error("chunk unavailable")),
  );
  try {
    await act(async () => {
      root.render(
        <>
          <main>Dashboard remains available</main>
          <OwnerPrankBoundary onFailure={onFailure}>
            <Suspense fallback={null}>
              <FailedChunk />
            </Suspense>
          </OwnerPrankBoundary>
        </>,
      );
    });
    expect(host.textContent).toBe("Dashboard remains available");
    expect(onFailure).toHaveBeenCalledTimes(1);
  } finally {
    act(() => root.unmount());
    host.remove();
    errorLog.mockRestore();
  }
});
