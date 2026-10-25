import { api } from './api'
import type { TodoSnapshot } from './todo'
export type TaskProgress = { snapshot: TodoSnapshot | null; updating: boolean; error?: string }
export async function loadTasks(onProgress: (data: TodoSnapshot, updating: boolean) => void, active: () => boolean) {
  const deadline = Date.now() + 110_000
  while (active()) {
    if (Date.now() >= deadline) throw new Error('Some task checks are taking too long. Please try again.')
    if (document.hidden) {
      await new Promise(resolve => setTimeout(resolve, 1000))
      continue
    }
    const result = await api<TaskProgress>('/todo?background=1')
    if (!active()) return
    if (result.snapshot) onProgress(result.snapshot, result.updating)
    if (result.error) throw new Error(result.error)
    if (!result.updating) return
    await new Promise(resolve => setTimeout(resolve, 750))
  }
}
