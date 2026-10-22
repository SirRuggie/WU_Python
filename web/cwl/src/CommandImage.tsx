import { useEffect, useRef, useState, type ComponentType } from 'react'
import { api, apiUpload } from './api'

type LibraryProps = { onClose: () => void; onChoose: (url: string) => void }

export function isDiscordImage(value: string) {
  try {
    const url = new URL(value)
    return url.protocol === 'https:' && ['cdn.discordapp.com', 'media.discordapp.net'].includes(url.hostname)
      && /\.(png|jpe?g|gif|webp)$/i.test(url.pathname)
  } catch { return false }
}

export default function CommandImage({ value, onChange, onBusy, label = 'Image link' }: {
  value: string; onChange: (url: string) => void; onBusy: (busy: boolean) => void; label?: string
}) {
  const [library, setLibrary] = useState(false)
  const [Library, setLibraryComponent] = useState<ComponentType<LibraryProps> | null>(null)
  const [libraryError, setLibraryError] = useState('')
  const libraryButton = useRef<HTMLButtonElement>(null)
  const [copied, setCopied] = useState(false)
  const [busy, setBusy] = useState(false), [error, setError] = useState(''), [stored, setStored] = useState('')

  useEffect(() => {
    if (!library || Library) return
    let active = true
    setLibraryError('')
    void import('./CommandImageLibrary').then(module => {
      if (active) setLibraryComponent(() => module.default)
    }).catch(() => {
      if (active) setLibraryError('The image picker could not load. Your edits are still here. Paste an image link, or save your changes and reload to try the picker again.')
    })
    return () => { active = false }
  }, [library, Library])

  function closeLibrary() {
    setLibrary(false)
    requestAnimationFrame(() => libraryButton.current?.focus())
  }

  async function transfer(file?: File) {
    if (file && (!file.size || file.size > 10 * 1024 * 1024)) {
      setError('Choose an image up to 10 MB.')
      return
    }
    setBusy(true); onBusy(true); setError('')
    try {
      const result = file
        ? await apiUpload<{ url: string }>('/manage/text-command-images/upload?name=' + encodeURIComponent(file.name), file)
        : await api<{ url: string }>('/manage/text-command-images/import', 'POST', { url: value })
      onChange(result.url); setStored(result.url)
    } catch (e) { setError(e instanceof Error ? e.message : 'Could not save the image.') }
    finally { setBusy(false); onBusy(false) }
  }

  return <div className="command-image-field">
    <label>{label}<input type="url" maxLength={1000} value={value} placeholder="Paste a direct image link" onChange={e => { onChange(e.target.value); setError('') }} /></label>
    <div className="command-image-tools">
      <button ref={libraryButton} type="button" disabled={busy} onClick={() => setLibrary(true)}>Choose image</button>
      <label className="command-image-upload">Upload image<input type="file" accept="image/png,image/jpeg,image/gif,image/webp" disabled={busy} onChange={e => { const file = e.target.files?.[0]; if (file) void transfer(file); e.target.value = '' }} /></label>
      {value.trim() && <button type="button" disabled={busy} onClick={() => void transfer()}>Save link to library</button>}
      {value && <button type="button" onClick={async () => {
        try { await navigator.clipboard.writeText(value); setCopied(true); setTimeout(() => setCopied(false), 2000) }
        catch { setError('Select the image link above and copy it.') }
      }}>{copied ? 'Copied' : 'Copy link'}</button>}
    </div>
    {busy ? <small role="status">Saving image…</small>
      : value === stored && stored ? <small role="status">Image stored permanently. Save the command to use it.</small>
      : isDiscordImage(value) ? <small>Discord image links are copied to permanent storage when you save.</small>
      : <small>Paste a link and select Save link to library, or upload a file. PNG, JPG, GIF or WebP · up to 10 MB</small>}
    {error && <p role="alert">{error}</p>}
    {library && !Library && <div>
      {libraryError ? <p role="alert">{libraryError}</p> : <p role="status">Loading image picker…</p>}
      <button type="button" onClick={closeLibrary}>Cancel image picker</button>
    </div>}
    {library && Library && <Library onClose={closeLibrary} onChoose={url => { onChange(url); closeLibrary() }} />}
  </div>
}
