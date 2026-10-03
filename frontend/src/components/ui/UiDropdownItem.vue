<template>
  <fluent-menu-item :disabled="disabled || loading" @click="handleClick"
    ><component
      :is="icon"
      v-if="icon"
      slot="start"
      :size="20"
      :stroke-width="1.5"
      aria-hidden="true" /><span class="button-content"
      ><fluent-progress-ring
        v-if="loading"
        class="button-progress"
        aria-label="处理中" /><slot /></span
  ></fluent-menu-item>
</template>
<script setup lang="ts">
import { inject, type Component } from 'vue'
const props = defineProps<{
  icon?: Component
  variant?: 'default' | 'danger'
  loading?: boolean
  disabled?: boolean
  onClick?: () => void | Promise<void>
}>()
const close = inject<() => void>('close-action-menu', () => {})
function handleClick() {
  if (props.loading || props.disabled) return
  close()
  props.onClick?.()
}
</script>
