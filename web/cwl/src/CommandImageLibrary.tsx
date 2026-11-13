import PageEyebrow from "./PageEyebrow";
import { useRef, useState } from "react";
import ActionPanel from "./ActionPanel";
import ImageCollection from "./ImageCollection";
export function ImageGallery({
  onDirty,
}: {
  onDirty?: (value: boolean) => void;
}) {
  return (
    <section className="image-gallery">
      <PageEyebrow />
      <h1>Image gallery</h1>
      <p>Find and organize images for commands and server messages.</p>
      <ImageCollection onDirty={onDirty} />
    </section>
  );
}
export default function CommandImageLibrary({
  onClose,
  onChoose,
  onDirty,
}: {
  onClose: () => void;
  onChoose: (url: string) => void;
  onDirty?: (value: boolean) => void;
}) {
  const guard = useRef<() => Promise<boolean>>(async () => true);
  // Focus returns here when the picker closes.
  const [opener] = useState(() =>
    document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null,
  );
  // The unsaved-edit check is async. Returning false makes Back re-push the
  // panel entry first; the check starts after that, so its own confirm entry
  // sits on top and is removed when it settles. The panel closes only after
  // the check allows it and the confirm entry is gone, so the panel can
  // remove its own entry when it unmounts.
  function close() {
    queueMicrotask(() => {
      void guard.current().then((leave) => {
        if (leave) afterConfirmEntryLeaves(onClose);
      });
    });
    return false;
  }
  return (
    <ActionPanel
      title="Select image"
      className="command-image-library roster-ui"
      trigger={opener}
      onClose={close}
    >
      <ImageCollection
        onDirty={onDirty}
        onChoose={onChoose}
        onGuard={(value) => {
          guard.current = value;
        }}
      />
    </ActionPanel>
  );
}

// A browser finishes history.back() on a later task. Wait for the confirm's
// own back move to land before running the next step.
function afterConfirmEntryLeaves(run: () => void) {
  const started = Date.now();
  const check = () => {
    const state: unknown = window.history.state;
    const marker =
      state && typeof state === "object"
        ? (state as Record<string, unknown>).wuActionPanel
        : undefined;
    const waiting =
      typeof marker === "string" && marker.startsWith("image-confirm-");
    if (!waiting || Date.now() - started > 1500) run();
    else window.setTimeout(check, 16);
  };
  check();
}
