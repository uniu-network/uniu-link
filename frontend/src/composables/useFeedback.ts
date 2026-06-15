import { inject, reactive, type InjectionKey } from 'vue'

type ToastType = 'success' | 'error' | 'warning' | 'info'

export interface ToastItem {
  id: number
  type: ToastType
  message: string
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
  confirmState: {
    open: boolean
    options: ConfirmOptions
    resolve?: (value: boolean) => void
  }
  toast: Record<ToastType, (message: string) => void>
  confirm: (options: ConfirmOptions) => Promise<boolean>
  closeToast: (id: number) => void
  resolveConfirm: (value: boolean) => void
}

export const feedbackKey: InjectionKey<FeedbackContext> = Symbol('feedback')

export function createFeedbackContext(): FeedbackContext {
  let toastId = 0
  const toasts = reactive<ToastItem[]>([])
  const confirmState = reactive({
    open: false,
    options: { title: '', content: '' } as ConfirmOptions,
    resolve: undefined as undefined | ((value: boolean) => void),
  })

  function closeToast(id: number) {
    const index = toasts.findIndex((toast) => toast.id === id)
    if (index >= 0) toasts.splice(index, 1)
  }

  function pushToast(type: ToastType, message: string) {
    const id = ++toastId
    toasts.push({ id, type, message })
    window.setTimeout(() => closeToast(id), 3200)
  }

  function confirm(options: ConfirmOptions) {
    confirmState.open = true
    confirmState.options = options
    return new Promise<boolean>((resolve) => {
      confirmState.resolve = resolve
    })
  }

  function resolveConfirm(value: boolean) {
    confirmState.open = false
    confirmState.resolve?.(value)
    confirmState.resolve = undefined
  }

  return {
    toasts,
    confirmState,
    toast: {
      success: (message) => pushToast('success', message),
      error: (message) => pushToast('error', message),
      warning: (message) => pushToast('warning', message),
      info: (message) => pushToast('info', message),
    },
    confirm,
    closeToast,
    resolveConfirm,
  }
}

export function useToast() {
  const context = inject(feedbackKey)
  if (!context) throw new Error('Feedback provider is missing')
  return context.toast
}

export function useConfirm() {
  const context = inject(feedbackKey)
  if (!context) throw new Error('Feedback provider is missing')
  return context.confirm
}
