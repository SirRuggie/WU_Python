import { act } from "react";

/** The search picker whose field label is exactly `label`. */
export function pickerByLabel(scope: ParentNode, label: string) {
  const found = [...scope.querySelectorAll<HTMLElement>(".search-picker")].find(
    (picker) =>
      picker.querySelector(".search-picker-label")?.textContent === label,
  );
  if (!found) throw new Error(`No search picker labelled "${label}"`);
  return found;
}

/** All search pickers in `scope`, in page order. */
export function allPickers(scope: ParentNode) {
  return [...scope.querySelectorAll<HTMLElement>(".search-picker")];
}

export async function openPicker(picker: HTMLElement) {
  await act(async () =>
    picker.querySelector<HTMLButtonElement>(".search-picker-trigger")!.click(),
  );
}

export async function typeInPicker(picker: HTMLElement, text: string) {
  const input = picker.querySelector<HTMLInputElement>(
    'input[role="combobox"]',
  )!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(
      HTMLInputElement.prototype,
      "value",
    )!.set!.call(input, text);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

/** Text of each row in the open list. */
export function optionTexts(picker: HTMLElement) {
  return [...picker.querySelectorAll('[role="option"]')].map(
    (node) => node.textContent,
  );
}

/** Clicks the row of an already open list that contains `text`. */
export async function clickOption(picker: HTMLElement, text: string) {
  const row = [...picker.querySelectorAll<HTMLElement>('[role="option"]')].find(
    (node) => node.textContent?.includes(text),
  );
  if (!row) throw new Error(`No picker row containing "${text}"`);
  await act(async () => row.click());
}

/** Opens the list, optionally searches, then clicks the row containing `text`. */
export async function pickOption(
  picker: HTMLElement,
  text: string,
  query?: string,
) {
  await openPicker(picker);
  if (query !== undefined) await typeInPicker(picker, query);
  await clickOption(picker, text);
}

/** Closed-field text of a picker. */
export function pickerValue(picker: HTMLElement) {
  return picker.querySelector(".search-picker-value")?.textContent ?? "";
}

export async function clearPicker(picker: HTMLElement) {
  await act(async () =>
    picker.querySelector<HTMLButtonElement>(".search-picker-clear")!.click(),
  );
}
