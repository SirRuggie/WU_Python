import { beforeEach, expect, it, vi } from 'vitest'
import { isValidElement, type ReactNode } from 'react'
const hooks = vi.hoisted(() => ({
  index: 0,
  ref: 0,
  values: [] as unknown[],
  refs: [] as { current: unknown }[],
  effects: [] as (() => unknown)[],
}))
const transport = vi.hoisted(() => vi.fn())
const upload = vi.hoisted(() => vi.fn())
vi.mock('react', async (original) => ({
  ...(await original<typeof import('react')>()),
  useState: (initial: unknown) => {
    const i = hooks.index++
    if (!(i in hooks.values))
      hooks.values[i] =
        typeof initial === 'function' ? (initial as () => unknown)() : initial
    return [
      hooks.values[i],
      (next: unknown) => {
        hooks.values[i] =
          typeof next === 'function'
            ? (next as (old: unknown) => unknown)(hooks.values[i])
            : next
      },
    ]
  },
  useRef: (initial: unknown) =>
    hooks.refs[hooks.ref++] ??
    (hooks.refs[hooks.ref - 1] = { current: initial }),
  useEffect: (effect: () => unknown) => {
    hooks.effects.push(effect)
  },
}))
vi.mock('./api', async (original) => ({
  ...(await original<typeof import('./api')>()),
  api: transport,
  apiUpload: upload,
}))
import ImageCollection, { type ImageItem } from './ImageCollection'
const image: ImageItem = {
  url: 'https://example.com/one.png',
  name: 'One',
  commands: [],
  folder: 'Clans',
  stored: true,
  archived: false,
}
function elements(
  node: ReactNode,
): { type: unknown; props: Record<string, unknown> }[] {
  if (Array.isArray(node)) return node.flatMap(elements)
  if (!isValidElement<Record<string, unknown>>(node)) return []
  return [
    { type: node.type, props: node.props },
    ...elements(node.props.children as ReactNode),
  ]
}
function draw() {
  hooks.index = 0
  hooks.ref = 0
  hooks.effects = []
  return elements(ImageCollection({}))
}
async function settle() {
  for (let i = 0; i < 12; i++) await Promise.resolve()
}
beforeEach(() => {
  hooks.values = []
  hooks.refs = []
  hooks.effects = []
  transport.mockReset()
  upload.mockReset()
})
it('opening the gallery only reads the catalog and never scans storage', async () => {
  transport.mockResolvedValue({ images: [image] })
  draw()
  hooks.effects[1]()
  await settle()
  expect(transport).toHaveBeenCalledTimes(1)
  expect(transport).toHaveBeenCalledWith('/manage/text-command-images')
})
it('partial bulk move retains only unconfirmed selections and reports progress', async () => {
  const second = { ...image, url: 'https://example.com/two.png', name: 'Two' }
  hooks.values = [
    [image, second],
    '',
    'active',
    '*',
    0,
    false,
    false,
    '',
    '',
    null,
    '',
    '',
    false,
    '',
    [],
    '',
    [image.url, second.url],
    'Tickets',
    '',
    [],
  ]
  transport
    .mockResolvedValueOnce({ ...image, folder: 'Tickets' })
    .mockRejectedValueOnce(new Error('Second move failed'))
    .mockResolvedValueOnce({
      images: [{ ...image, folder: 'Tickets' }, second],
    })
  const button = draw().find(
    (node) => node.type === 'button' && node.props.children === 'Move images',
  )!
  ;(button.props.onClick as () => void)()
  await settle()
  expect(hooks.values[16]).toEqual([second.url])
  expect(hooks.values[8]).toContain('1 of 2 images moved')
  expect(hooks.values[7]).toBe('Second move failed')
  expect(transport.mock.calls[0][2].expected).toEqual({
    name: 'One',
    folder: 'Clans',
    archived: false,
  })
})
it('validates the full file batch before uploading the first file', async () => {
  hooks.values = [
    [],
    '',
    'active',
    '*',
    0,
    false,
    false,
    '',
    '',
    null,
    '',
    '',
    true,
    '',
    [
      { name: 'good.png', size: 20 },
      { name: 'large.png', size: 11 * 1024 * 1024 },
    ],
    '',
    [],
    '',
    '',
    [],
  ]
  const button = draw().find(
    (node) => node.type === 'button' && node.props.children === 'Save images',
  )!
  ;(button.props.onClick as () => void)()
  await settle()
  expect(upload).not.toHaveBeenCalled()
  expect(transport).not.toHaveBeenCalled()
  expect(hooks.values[7]).toContain('large.png')
})
