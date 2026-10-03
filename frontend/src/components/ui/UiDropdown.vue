<template>
  <span ref="trigger" class="dropdown-trigger"
    ><UiButton
      variant="ghost"
      size="icon"
      aria-label="更多操作"
      title="更多操作"
      aria-haspopup="menu"
      :aria-expanded="open"
      @click.stop="open = !open"
      ><NavIcon name="more" /></UiButton
  ></span>
  <Teleport to="body"
    ><fluent-menu
      v-if="open"
      ref="menu"
      class="action-menu"
      :style="position"
      @keydown.esc.stop.prevent="close(true)"
      @keydown.tab="close()"
      ><slot /></fluent-menu
  ></Teleport>
</template>
<script setup lang="ts">
import { nextTick, onBeforeUnmount, onMounted, provide, ref, watch } from 'vue'
import UiButton from './UiButton.vue'
import NavIcon from '@/components/NavIcon.vue'
const open = defineModel<boolean>('open', { default: false })
const trigger = ref<HTMLElement>()
const menu = ref<HTMLElement>()
const position = ref<Record<string, string>>({})
function close(restore = false) {
  open.value = false
  if (restore) trigger.value?.querySelector<HTMLElement>('fluent-button')?.focus()
}
provide('close-action-menu', () => close(true))
function positionMenu() {
  const bounds = trigger.value?.getBoundingClientRect()
  if (!bounds || !menu.value) return
  const height = menu.value.getBoundingClientRect().height
  position.value = {
    top: `${Math.max(8, bounds.bottom + height + 8 > innerHeight ? bounds.top - height - 6 : bounds.bottom + 6)}px`,
    right: `${Math.max(8, innerWidth - bounds.right)}px`,
  }
}
watch(open, async (value) => {
  if (!value) return
  await nextTick()
  positionMenu()
  await nextTick()
  menu.value?.querySelector<HTMLElement>('fluent-menu-item')?.focus({ preventScroll: true })
})
function outside(event: MouseEvent) {
  if (!event.composedPath().includes(trigger.value!) && !event.composedPath().includes(menu.value!))
    close()
}
function reposition() {
  if (open.value) positionMenu()
}
onMounted(() => {
  document.addEventListener('click', outside, true)
  window.addEventListener('resize', reposition)
  window.addEventListener('scroll', reposition, true)
})
onBeforeUnmount(() => {
  document.removeEventListener('click', outside, true)
  window.removeEventListener('resize', reposition)
  window.removeEventListener('scroll', reposition, true)
})
</script>
