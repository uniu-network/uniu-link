<script setup lang="ts">
import { onBeforeUnmount, onMounted } from 'vue'
import NavIcon from './NavIcon.vue'
import type { MessageType } from '@/composables/useFeedback'

const props = withDefaults(
  defineProps<{ message: string; type?: MessageType; duration?: number }>(),
  { type: 'success' }
)
const emit = defineEmits<{ close: [] }>()
let remaining = props.duration ?? (props.type === 'success' ? 3500 : 8000)
let timer: ReturnType<typeof setTimeout> | undefined
let started = 0
let hovered = false
let focused = false

function resume() {
  if (hovered || focused || timer !== undefined || props.duration === 0) return
  started = performance.now()
  timer = setTimeout(() => {
    timer = undefined
    emit('close')
  }, remaining)
}
function pause() {
  if (timer === undefined) return
  clearTimeout(timer)
  timer = undefined
  remaining = Math.max(0, remaining - (performance.now() - started))
}
function mouseEnter() {
  hovered = true
  pause()
}
function mouseLeave() {
  hovered = false
  resume()
}
function focusIn() {
  focused = true
  pause()
}
function focusOut(event: FocusEvent) {
  if (
    event.relatedTarget instanceof Node &&
    (event.currentTarget as HTMLElement).contains(event.relatedTarget)
  )
    return
  focused = false
  resume()
}
onMounted(resume)
onBeforeUnmount(() => clearTimeout(timer))
</script>

<template>
  <div
    class="message-item"
    @mouseenter="mouseEnter"
    @mouseleave="mouseLeave"
    @focusin="focusIn"
    @focusout="focusOut"
  >
    <fluent-card>
      <div class="message-content">
        <span class="message-symbol" :class="`message-symbol-${type}`"
          ><NavIcon :name="type"
        /></span>
        <span
          class="message-text"
          :role="type === 'error' ? 'alert' : 'status'"
          aria-atomic="true"
          >{{ message }}</span
        >
        <fluent-button
          appearance="stealth"
          aria-label="关闭消息"
          title="关闭消息"
          @click="emit('close')"
          ><NavIcon name="close" :size="16"
        /></fluent-button>
      </div>
    </fluent-card>
  </div>
</template>
