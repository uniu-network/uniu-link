import { inject, reactive, type InjectionKey } from 'vue'

export type MessageType = 'success' | 'error' | 'warning'
type ToastType = MessageType | 'info'
export interface ToastItem {
  id: number
  type: MessageType
  message: string
  duration?: number
}
export interface ConfirmOptions {
  title: string
  content: string
  positiveText?: string
  negativeText?: string
  variant?: 'default' | 'danger'
}
export interface FeedbackContext {
  toasts: ToastItem[]
  confirmState: { open: boolean; options: ConfirmOptions }
  toast: Record<ToastType, (message: string, duration?: number) => void>
  notify: (message: string, type?: MessageType, duration?: number) => number
  confirm: (options: ConfirmOptions) => Promise<boolean>
  closeToast: (id: number) => void
  resolveConfirm: (value: boolean) => void
}
export const feedbackKey: InjectionKey<FeedbackContext> = Symbol('feedback')
export function createFeedbackContext(): FeedbackContext {
  let nextId = 0
  const toasts = reactive<ToastItem[]>([])
  const confirmState = reactive({
    open: false,
    options: { title: '', content: '' } as ConfirmOptions,
  })
  const queue: { options: ConfirmOptions; resolve: (value: boolean) => void }[] = []
  function notify(message: string, type: MessageType = 'success', duration?: number) {
    const id = ++nextId
    toasts.push({ id, type, message, duration })
    if (toasts.length > 5) toasts.splice(0, toasts.length - 5)
    return id
  }
  function closeToast(id: number) {
    const index = toasts.findIndex((item) => item.id === id)
    if (index !== -1) toasts.splice(index, 1)
  }
  function showNext() {
    if (!queue.length) return
    confirmState.options = queue[0].options
    confirmState.open = true
  }
  function confirm(options: ConfirmOptions): Promise<boolean> {
    return new Promise((resolve) => {
      queue.push({ options, resolve })
      if (queue.length === 1) showNext()
    })
  }
  function resolveConfirm(value: boolean) {
    if (!confirmState.open) return
    confirmState.open = false
    queue.shift()?.resolve(value)
    // Allow the old dialog to unmount and restore focus before displaying the next one.
    queueMicrotask(showNext)
  }
  return {
    toasts,
    confirmState,
    notify,
    confirm,
    closeToast,
    resolveConfirm,
    toast: {
      success: (m, d) => notify(m, 'success', d),
      error: (m, d) => notify(m, 'error', d),
      warning: (m, d) => notify(m, 'warning', d),
      info: (m, d) => notify(m, 'success', d),
    },
  }
}
export const feedback = createFeedbackContext()
export const notify = feedback.notify
export function useToast() {
  return inject(feedbackKey, feedback).toast
}
export function useConfirm() {
  return inject(feedbackKey, feedback).confirm
}
