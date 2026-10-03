import { reactive } from 'vue'
// Only the top dialog owns keyboard focus, including a confirmation above an editor.
export const dialogStack = reactive<{ id: symbol; dismiss: () => void; suspend: () => void }[]>([])
let savedOverflow = ''
function escape(event: KeyboardEvent) {
  if (event.key !== 'Escape' || !dialogStack.length) return
  event.preventDefault()
  event.stopImmediatePropagation()
  // FAST reflects attributes on the next frame. Read the public property so
  // an immediate Escape closes a just-opened list without dismissing its dialog.
  const select = event.composedPath().find(
    (element): element is HTMLElement & { open: boolean } =>
      element instanceof HTMLElement &&
      element.localName === 'fluent-select' &&
      (element as HTMLElement & { open: boolean }).open
  )
  if (select) {
    select.open = false
    return
  }
  dialogStack[dialogStack.length - 1].dismiss()
}
export function addDialog(id: symbol, dismiss: () => void, suspend: () => void) {
  dialogStack[dialogStack.length - 1]?.suspend()
  if (!dialogStack.length) {
    savedOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    document.addEventListener('keydown', escape, true)
  }
  dialogStack.push({ id, dismiss, suspend })
}
export function removeDialog(id: symbol) {
  const index = dialogStack.findIndex((dialog) => dialog.id === id)
  if (index !== -1) dialogStack.splice(index, 1)
  if (!dialogStack.length) {
    document.body.style.overflow = savedOverflow
    document.removeEventListener('keydown', escape, true)
  }
}
