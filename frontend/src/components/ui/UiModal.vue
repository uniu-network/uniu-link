<template>
  <Teleport to="body">
    <fluent-dialog
      v-if="open"
      ref="dialog"
      :modal.prop="true"
      :trapFocus.prop="true"
      :hidden.prop="!topmost"
      :aria-label="title"
      :style="dialogGeometry"
      class="app-dialog"
      @dismiss="requestClose"
    >
      <div class="dialog-body" @keydown="saveShortcut">
        <header class="dialog-heading">
          <h2>{{ title }}</h2>
          <UiButton
            variant="ghost"
            size="icon"
            :disabled="busy"
            aria-label="关闭对话框"
            title="关闭"
            @click="requestClose"
            ><NavIcon name="close" :size="16"
          /></UiButton>
        </header>
        <div class="dialog-content"><slot /></div>
        <footer v-if="$slots.footer" class="dialog-footer">
          <fluent-divider />
          <div class="actions dialog-actions"><slot name="footer" /></div>
        </footer>
      </div>
    </fluent-dialog>
  </Teleport>
</template>
<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, provide, ref, watch } from 'vue'
import NavIcon from '@/components/NavIcon.vue'
import UiButton from './UiButton.vue'
import { addDialog, dialogStack, removeDialog } from '@/composables/useDialogStack'
import { formBusyKey } from '@/composables/useField'
const props = withDefaults(
  defineProps<{
    open: boolean
    title?: string
    width?: string
    busy?: boolean
    beforeClose?: () => Promise<boolean>
  }>(),
  { width: '640px' }
)
const emit = defineEmits<{ 'update:open': [value: boolean]; save: [] }>()
const id = Symbol('dialog')
const dialog = ref<HTMLElement & { hide: () => void }>()
const topmost = computed(() => dialogStack[dialogStack.length - 1]?.id === id)
// Public dialog size hooks only control geometry; Fluent retains its surface, border,
// corner radius, shadow, overlay and focus treatment.
const dialogGeometry = computed(() => ({
  '--dialog-width': `min(${props.width}, calc(100vw - 34px))`,
  '--dialog-height': 'auto',
  zIndex:
    1000 +
    Math.max(
      0,
      dialogStack.findIndex((item) => item.id === id)
    ),
}))
provide(
  formBusyKey,
  computed(() => !!props.busy)
)
let previousFocus: HTMLElement | null = null
let closing = false
function saveShortcut(event: KeyboardEvent) {
  if (event.key.toLowerCase() === 's' && (event.ctrlKey || event.metaKey)) {
    event.preventDefault()
    if (topmost.value && !props.busy) emit('save')
  }
}
async function requestClose() {
  if (!topmost.value || props.busy || closing) return
  closing = true
  try {
    if (!props.beforeClose || (await props.beforeClose())) emit('update:open', false)
  } finally {
    closing = false
  }
}
watch(
  () => props.open,
  async (open) => {
    if (open) {
      previousFocus = document.activeElement as HTMLElement | null
      // Suspend via the public hidden lifecycle: FAST 2.6.1 does not reliably
      // refresh an already connected dialog's trap when trapFocus changes.
      // The editor stays mounted with every field intact behind the confirmation.
      addDialog(
        id,
        () => {
          void requestClose()
        },
        () => dialog.value?.hide()
      )
    } else {
      dialog.value?.hide()
      removeDialog(id)
      await nextTick()
      if (previousFocus?.isConnected) previousFocus.focus()
    }
  },
  { immediate: true, flush: 'pre' }
)
onBeforeUnmount(() => {
  dialog.value?.hide()
  removeDialog(id)
  if (previousFocus?.isConnected) previousFocus.focus()
})
</script>
