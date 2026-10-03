import { computed, onBeforeUnmount, watch, type Ref } from 'vue'
import { feedback } from './useFeedback'
const drafts = new Map<symbol, () => boolean>()
let approvedNavigation = false
const discardOptions = {
  title: '放弃未保存的修改？',
  content: '当前修改尚未保存，离开后将丢失。',
  positiveText: '放弃修改',
  negativeText: '继续编辑',
}
export function hasUnsavedChanges() {
  return [...drafts.values()].some((dirty) => dirty())
}
export async function confirmUnsavedChanges() {
  return !hasUnsavedChanges() || (await feedback.confirm(discardOptions))
}
export function approveNextNavigation() {
  approvedNavigation = true
}
export function clearNavigationApproval() {
  approvedNavigation = false
}
export async function guardUnsavedChanges() {
  return approvedNavigation || (await confirmUnsavedChanges())
}
function beforeUnload(event: BeforeUnloadEvent) {
  if (hasUnsavedChanges()) {
    event.preventDefault()
    event.returnValue = ''
  }
}
function registerDraft(dirty: () => boolean) {
  const id = Symbol('draft')
  drafts.set(id, dirty)
  if (drafts.size === 1) window.addEventListener('beforeunload', beforeUnload)
  onBeforeUnmount(() => {
    drafts.delete(id)
    if (!drafts.size) window.removeEventListener('beforeunload', beforeUnload)
  })
}
export function useUnsavedForm(open: Ref<boolean>, value: () => unknown, busy?: Ref<boolean>) {
  let baseline = ''
  watch(
    open,
    (visible) => {
      if (visible) baseline = JSON.stringify(value())
    },
    { flush: 'sync' }
  )
  const dirty = computed(() => open.value && JSON.stringify(value()) !== baseline)
  registerDraft(() => dirty.value || (open.value && !!busy?.value))
  async function beforeClose() {
    if (busy?.value) return false
    return !dirty.value || (await feedback.confirm(discardOptions))
  }
  async function closeEditor() {
    if (await beforeClose()) open.value = false
  }
  return { dirty, beforeClose, closeEditor }
}
export function useDraftGuard(dirty: () => boolean) {
  registerDraft(dirty)
}
