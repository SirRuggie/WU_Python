import { useEffect, useRef, useState } from 'react'
import { api, apiUpload, ApiError } from './api'
import { imageCategory, defaultImageCategories } from './imageCategories'
import './ImageGallery.css'
export type ImageItem = {
  url: string
  name: string
  commands: string[]
  stored: boolean
  archived: boolean
  folder?: string
}
const expected = (item: ImageItem) => ({
  name: item.name,
  folder: item.folder || '',
  archived: item.archived,
})
export default function ImageCollection({
  onChoose,
  onDirty,
  onGuard,
}: {
  onChoose?: (url: string) => void
  onDirty?: (value: boolean) => void
  onGuard?: (guard: () => boolean) => void
}) {
  const [images, setImages] = useState<ImageItem[]>([]),
    [query, setQuery] = useState(''),
    [filter, setFilter] = useState('active'),
    [folder, setFolder] = useState('*'),
    [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(''),
    [notice, setNotice] = useState('')
  const [editing, setEditing] = useState<ImageItem | null>(null),
    [name, setName] = useState(''),
    [category, setCategory] = useState('')
  const [adding, setAdding] = useState(false),
    [link, setLink] = useState(''),
    [files, setFiles] = useState<File[]>([]),
    [uploadCategory, setUploadCategory] = useState('')
  const [selected, setSelected] = useState<string[]>([]),
    [destination, setDestination] = useState(''),
    [copied, setCopied] = useState('')
  const [failed, setFailed] = useState<string[]>([])
  const alive = useRef(true),
    operation = useRef(false),
    sequence = useRef(0)
  const dirty =
    !!(
      editing &&
      (name !== editing.name || category !== imageCategory(editing.folder))
    ) ||
    !!link.trim() ||
    files.length > 0
  const guard = () =>
    !operation.current &&
    (!dirty ||
      window.confirm('Discard unsaved image details or pending uploads?'))
  useEffect(() => {
    onDirty?.(dirty || busy)
    onGuard?.(guard)
    const protect = (e: BeforeUnloadEvent) => {
      if (dirty || busy) {
        e.preventDefault()
        e.returnValue = ''
      }
    }
    window.addEventListener('beforeunload', protect)
    return () => {
      onDirty?.(false)
      window.removeEventListener('beforeunload', protect)
    }
  }, [dirty, busy, onDirty, onGuard])
  function failure(e: unknown, fallback: string) {
    if (e instanceof ApiError && [401, 403].includes(e.status)) {
      setImages([])
      setSelected([])
      setEditing(null)
      setFiles([])
      setLink('')
    }
    setError(e instanceof Error ? e.message : fallback)
  }
  async function load() {
    const turn = ++sequence.current
    setLoading(true)
    try {
      const result = await api<{ images: ImageItem[] }>(
        '/manage/text-command-images',
      )
      if (alive.current && turn === sequence.current) {
        setImages(result.images)
        setFailed([])
      }
    } catch (e) {
      if (alive.current && turn === sequence.current)
        failure(e, 'Could not load images.')
    } finally {
      if (alive.current && turn === sequence.current) setLoading(false)
    }
  }
  useEffect(() => {
    alive.current = true
    void load()
    return () => {
      alive.current = false
      sequence.current++
    }
  }, [])
  useEffect(() => setPage(0), [query, filter, folder])
  async function run(action: () => Promise<void>) {
    if (operation.current) return
    operation.current = true
    sequence.current++
    setLoading(false)
    setBusy(true)
    setError('')
    setNotice('')
    try {
      await action()
    } catch (e) {
      if (alive.current)
        failure(
          e,
          'The change could not be confirmed. Refresh the gallery before trying again.',
        )
    } finally {
      operation.current = false
      if (alive.current) setBusy(false)
    }
  }
  async function update(item: ImageItem, changes: Partial<ImageItem>) {
    return api<ImageItem>('/manage/text-command-images', 'PATCH', {
      url: item.url,
      ...expected(item),
      ...changes,
      expected: expected(item),
    })
  }
  async function saveDetails(item: ImageItem) {
    await run(async () => {
      const result = await update(item, {
        name: name.trim(),
        folder:
          category === imageCategory(item.folder)
            ? item.folder || ''
            : category.trim(),
      })
      setImages((rows) =>
        rows.map((row) => (row.url === item.url ? result : row)),
      )
      setEditing(null)
      setNotice('Image details saved. Links stay the same.')
    })
  }
  async function archive(item: ImageItem) {
    if (!guard()) return
    await run(async () => {
      const result = await update(item, { archived: !item.archived })
      setImages((rows) =>
        rows.map((row) => (row.url === item.url ? result : row)),
      )
      setSelected((rows) => rows.filter((url) => url !== item.url))
      setEditing(null)
      setNotice(
        result.archived
          ? 'Image archived. Existing messages still work.'
          : 'Image restored to the gallery.',
      )
    })
  }
  async function moveSelected() {
    if (!guard()) return
    await run(async () => {
      const completed: string[] = []
      try {
        for (const url of selected) {
          if (!alive.current) break
          const item = images.find((row) => row.url === url)
          if (!item) continue
          await update(item, { folder: destination.trim() })
          completed.push(url)
        }
      } finally {
        setSelected((rows) => rows.filter((url) => !completed.includes(url)))
        setNotice(
          `${completed.length} of ${selected.length} images moved. Any remaining selections were not confirmed.`,
        )
        await load()
      }
    })
  }
  async function upload() {
    await run(async () => {
      let count = 0
      // Validate every file before beginning the batch.
      for (const file of files)
        if (!file.size || file.size > 10 * 1024 * 1024)
          throw new Error(`${file.name}: choose an image up to 10 MB.`)
      try {
        if (files.length) {
          for (const file of files) {
            if (!alive.current) break
            await apiUpload(
              '/manage/text-command-images/upload?name=' +
                encodeURIComponent(file.name) +
                '&category=' +
                encodeURIComponent(uploadCategory.trim()),
              file,
            )
            count++
            setFiles((rows) => rows.filter((row) => row !== file))
          }
        } else {
          await api('/manage/text-command-images/import', 'POST', {
            url: link.trim(),
            category: uploadCategory.trim(),
          })
          count++
          setLink('')
        }
        setFolder(imageCategory(uploadCategory))
        setAdding(false)
      } finally {
        setNotice(
          `${count} image${count === 1 ? '' : 's'} added. Check the gallery before retrying an interrupted upload.`,
        )
        await load()
      }
    })
  }
  async function sync() {
    await run(async () => {
      let cursor: string | null = null,
        count = 0
      const seen = new Set<string>()
      do {
        const result: { indexed: number; cursor: string | null } = await api(
          '/manage/text-command-images/sync',
          'POST',
          { cursor },
        )
        count += result.indexed
        cursor = result.cursor
        if (cursor && seen.has(cursor))
          throw new Error(
            'Storage refresh stopped because the next page repeated. Saved images are still available.',
          )
        if (cursor) seen.add(cursor)
      } while (cursor && alive.current)
      setNotice(`Storage checked · ${count} images found.`)
      await load()
    })
  }
  const folders = [
    ...new Set([
      ...defaultImageCategories,
      ...images.map((item) => imageCategory(item.folder)).filter(Boolean),
    ]),
  ].sort()
  const matches = images.filter(
    (item) =>
      (filter === 'archived' ? item.archived : !item.archived) &&
      (filter !== 'used' || item.commands.length > 0) &&
      (filter !== 'unused' || !item.commands.length) &&
      (folder === '*' || imageCategory(item.folder) === folder) &&
      [item.name, item.folder || '', ...item.commands].some((value) =>
        value.toLowerCase().includes(query.trim().toLowerCase()),
      ),
  )
  const pages = Math.max(1, Math.ceil(matches.length / 24)),
    current = Math.min(page, pages - 1)
  return (
    <div className="image-collection">
      <div className="gallery-toolbar">
        <button
          className="primary"
          disabled={busy}
          onClick={() => {
            if (!guard()) return
            setEditing(null)
            setLink('')
            setFiles([])
            setUploadCategory(folder === '*' ? '' : folder)
            setAdding(!adding)
          }}
        >
          {adding ? 'Cancel adding' : '+ Add images'}
        </button>
        <button
          disabled={busy || loading}
          onClick={() => {
            if (!guard()) return
            setEditing(null)
            setLink('')
            setFiles([])
            setError('')
            setNotice('')
            void load()
          }}
        >
          Refresh gallery
        </button>
      </div>
      {error && (
        <p className="notice error" role="alert">
          {error}
        </p>
      )}
      {notice && <p role="status">{notice}</p>}
      {adding && (
        <section className="gallery-upload" aria-label="Add images">
          <label>
            Category
            <input
              disabled={busy}
              list="gallery-folder-options"
              maxLength={120}
              value={uploadCategory}
              onChange={(e) => setUploadCategory(e.target.value)}
              placeholder="Unsorted"
            />
          </label>
          <label>
            Choose files
            <input
              type="file"
              multiple
              disabled={busy || !!link.trim()}
              accept="image/png,image/jpeg,image/gif,image/webp"
              onChange={(e) => {
                setFiles(Array.from(e.target.files || []))
                e.target.value = ''
              }}
            />
          </label>
          {files.length > 0 && (
            <p>
              {files.length} selected ·{' '}
              {files.map((file) => file.name).join(', ')}
            </p>
          )}
          <label>
            Or paste an image link
            <input
              type="url"
              disabled={busy || files.length > 0}
              value={link}
              onChange={(e) => setLink(e.target.value)}
              placeholder="https://…"
            />
          </label>
          <small>
            PNG, JPG, GIF or WebP · up to 10 MB each. Images are added when you
            save.
          </small>
          <button
            disabled={busy || (!files.length && !link.trim())}
            onClick={() => void upload()}
          >
            {busy ? 'Adding…' : 'Save images'}
          </button>
        </section>
      )}
      <div className="gallery-filters">
        <label>
          Find an image
          <input
            type="search"
            value={query}
            onChange={(e) => {
              if (!guard()) return
              setEditing(null)
              setQuery(e.target.value)
            }}
            placeholder="Name, category or command"
          />
        </label>
        <label>
          Category
          <select
            disabled={busy}
            value={folder}
            onChange={(e) => {
              if (!guard()) return
              setEditing(null)
              setFolder(e.target.value)
              setSelected([])
            }}
          >
            <option value="*">All images</option>
            {folders.map((value) => (
              <option key={value}>{value}</option>
            ))}
            <option value="">Unsorted</option>
          </select>
        </label>
        <label>
          Show
          <select
            disabled={busy}
            value={filter}
            onChange={(e) => {
              if (!guard()) return
              setEditing(null)
              setFilter(e.target.value)
              setSelected([])
            }}
          >
            <option value="active">Available</option>
            <option value="used">Used by commands</option>
            <option value="unused">No command use</option>
            <option value="archived">Archived</option>
          </select>
        </label>
      </div>
      {selected.length > 0 && (
        <section className="gallery-bulk" aria-label="Move selected images">
          <strong>{selected.length} selected</strong>
          <label>
            Move to category
            <input
              disabled={busy}
              value={destination}
              list="gallery-folder-options"
              maxLength={120}
              onChange={(e) => setDestination(e.target.value)}
            />
          </label>
          <button
            disabled={busy || !destination.trim()}
            onClick={() => void moveSelected()}
          >
            Move images
          </button>
          <button disabled={busy} onClick={() => setSelected([])}>
            Clear selection
          </button>
        </section>
      )}
      {loading ? (
        <p role="status">Loading images…</p>
      ) : (
        <>
          <p className="small">
            {matches.length} images · {selected.length} selected
          </p>
          <div className="command-image-grid">
            {matches.slice(current * 24, (current + 1) * 24).map((item) => (
              <article key={item.url}>
                <label className="gallery-select">
                  <input
                    type="checkbox"
                    disabled={busy}
                    checked={selected.includes(item.url)}
                    onChange={(e) =>
                      setSelected((rows) =>
                        e.target.checked
                          ? [...rows, item.url]
                          : rows.filter((url) => url !== item.url),
                      )
                    }
                  />
                  <strong>{item.name}</strong>
                </label>
                {failed.includes(item.url) ? (
                  <div className="image-unavailable">Preview unavailable</div>
                ) : (
                  <a
                    href={item.url}
                    target="_blank"
                    rel="noreferrer"
                    aria-label={`Open ${item.name}`}
                  >
                    <img
                      loading="lazy"
                      src={item.url}
                      alt={item.name}
                      onError={() => setFailed((rows) => [...rows, item.url])}
                    />
                  </a>
                )}
                <small>
                  {imageCategory(item.folder) || 'Unsorted'} ·{' '}
                  {item.commands.length} command
                  {item.commands.length === 1 ? '' : 's'}
                </small>
                <div className="gallery-card-actions">
                  {onChoose && (
                    <button
                      className="primary"
                      disabled={busy || item.archived}
                      onClick={() => {
                        if (guard()) onChoose(item.url)
                      }}
                    >
                      Use image
                    </button>
                  )}
                  {!onChoose && (
                    <button
                      onClick={async () => {
                        try {
                          await navigator.clipboard.writeText(item.url)
                          setCopied(item.url)
                        } catch {
                          setError('Open the image and copy its address.')
                        }
                      }}
                    >
                      {copied === item.url ? 'Copied' : 'Copy link'}
                    </button>
                  )}
                  <button
                    disabled={busy}
                    aria-expanded={editing?.url === item.url}
                    onClick={() => {
                      if (!guard()) return
                      setEditing(editing?.url === item.url ? null : item)
                      setName(item.name)
                      setCategory(imageCategory(item.folder))
                    }}
                  >
                    Details
                  </button>
                </div>
                {editing?.url === item.url && (
                  <div className="gallery-edit">
                    <label>
                      Name
                      <input
                        disabled={busy}
                        maxLength={120}
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                      />
                    </label>
                    <label>
                      Category
                      <input
                        disabled={busy}
                        maxLength={120}
                        list="gallery-folder-options"
                        value={category}
                        onChange={(e) => setCategory(e.target.value)}
                      />
                    </label>
                    <p>
                      {item.commands.length
                        ? `Commands: ${item.commands.join(', ')}`
                        : 'No command use found. This image may be used elsewhere.'}
                    </p>
                    <p>
                      Names and categories keep the same link. Archiving hides
                      the image without breaking existing messages.
                    </p>
                    <button
                      disabled={busy || !name.trim() || !dirty}
                      onClick={() => void saveDetails(item)}
                    >
                      Save details
                    </button>
                    <button disabled={busy} onClick={() => void archive(item)}>
                      {item.archived ? 'Restore image' : 'Archive image'}
                    </button>
                  </div>
                )}
              </article>
            ))}
          </div>
          {!matches.length && !error && (
            <p>No images match. Change filters or add an image.</p>
          )}
          {pages > 1 && (
            <nav className="gallery-pages" aria-label="Image pages">
              <button
                disabled={busy || current === 0}
                onClick={() => {
                  if (guard()) {
                    setEditing(null)
                    setPage(current - 1)
                  }
                }}
              >
                Previous
              </button>
              <span>
                Page {current + 1} of {pages}
              </span>
              <button
                disabled={busy || current === pages - 1}
                onClick={() => {
                  if (guard()) {
                    setEditing(null)
                    setPage(current + 1)
                  }
                }}
              >
                Next
              </button>
            </nav>
          )}
        </>
      )}
      <details className="gallery-storage">
        <summary>Storage tools</summary>
        <p>
          Look for images added outside this gallery. Existing names and
          categories are kept.
        </p>
        <button
          disabled={busy || loading}
          onClick={() => {
            if (guard()) void sync()
          }}
        >
          Check storage for images
        </button>
      </details>
      <datalist id="gallery-folder-options">
        {folders.map((value) => (
          <option key={value} value={value} />
        ))}
      </datalist>
    </div>
  )
}
