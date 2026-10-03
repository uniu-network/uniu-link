<template>
  <fluent-button
    :appearance="appearance"
    :type="nativeType"
    :disabled="disabled || loading || formBusy"
    :aria-busy="loading || undefined"
    :class="{ 'button-block': block }"
  >
    <span class="button-content"
      ><fluent-progress-ring v-if="loading" class="button-progress" aria-label="处理中" /><slot
    /></span>
  </fluent-button>
</template>
<script setup lang="ts">
import { computed, inject } from 'vue'
import { formBusyKey } from '@/composables/useField'
const formBusy = inject(
  formBusyKey,
  computed(() => false)
)
const props = withDefaults(
  defineProps<{
    variant?: 'default' | 'primary' | 'danger' | 'ghost' | 'link'
    size?: 'sm' | 'md' | 'lg' | 'icon'
    block?: boolean
    loading?: boolean
    disabled?: boolean
    nativeType?: 'button' | 'submit' | 'reset'
  }>(),
  { variant: 'default', nativeType: 'button' }
)
const appearance = computed(() =>
  props.size === 'icon' || props.variant === 'ghost'
    ? 'stealth'
    : props.variant === 'primary' || props.variant === 'danger'
      ? 'accent'
      : props.variant === 'link'
        ? 'lightweight'
        : 'neutral'
)
</script>
