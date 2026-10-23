import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import ImageCollection from './ImageCollection'
export function ImageGallery({
  onDirty,
}: {
  onDirty?: (value: boolean) => void
}) {
  return (
    <section className="image-gallery">
      <p className="eyebrow">Settings</p>
      <h1>Image Gallery</h1>
      <p>Find and organize images for commands and server messages.</p>
      <ImageCollection onDirty={onDirty} />
    </section>
  )
}
export default function CommandImageLibrary({
  onClose,
  onChoose,
  onDirty,
}: {
  onClose: () => void
  onChoose: (url: string) => void
  onDirty?: (value: boolean) => void
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    guard = useRef<() => boolean>(() => true)
  useEffect(() => {
    const element = dialog.current
    element?.showModal()
    return () => element?.close()
  }, [])
  function close() {
    if (guard.current()) onClose()
  }
  return createPortal(
    <dialog
      ref={dialog}
      className="command-image-library"
      onCancel={(e) => {
        e.preventDefault()
        close()
      }}
      aria-labelledby="image-library-title"
    >
      <header>
        <h2 id="image-library-title">Choose image</h2>
        <button type="button" onClick={close} aria-label="Close image library">
          Close ×
        </button>
      </header>
      <ImageCollection
        onDirty={onDirty}
        onChoose={onChoose}
        onGuard={(value) => {
          guard.current = value
        }}
      />
    </dialog>,
    document.body,
  )
}
