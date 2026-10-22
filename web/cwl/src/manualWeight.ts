/** Manual CWL overrides use five storages; the API still receives full weight. */
export type ManualWeightDraft = { unit: 'loot' | 'full'; text: string }
export function manualWeightDraft(weight: number | null): ManualWeightDraft {
  return { unit: 'full', text: weight === null ? '' : String(weight) }
}
export function parseManualWeight(draft: ManualWeightDraft): number | null {
  const text = draft.text.trim().replace(/,/g, '')
  if (!text) return null
  if (!/^\d+(\.\d+)?$/.test(text)) throw new Error('Enter loot or full weight as a number.')
  const weight = Number(text) * (draft.unit === 'loot' ? 5 : 1)
  if (!Number.isSafeInteger(weight) || weight < 1 || weight > 500000)
    throw new Error('Full weight must be a whole number from 1 to 500,000. Loot is multiplied by 5.')
  return weight
}
export function manualWeightFields(draft: ManualWeightDraft) {
  let weight: number | null = null
  try { weight = parseManualWeight(draft) } catch { /* Keep invalid input editable. */ }
  return {
    loot: draft.unit === 'loot' ? draft.text : weight === null ? '' : String(weight / 5),
    full: draft.unit === 'full' ? draft.text : weight === null ? '' : String(weight),
  }
}
