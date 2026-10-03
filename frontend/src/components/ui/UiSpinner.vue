<template>
  <div v-if="show" class="loading-state" role="status" aria-live="polite">
    <fluent-progress-ring :aria-label="label" /><span>{{ label }}</span>
  </div>
  <slot v-else />
</template>
<script setup lang="ts">
withDefaults(defineProps<{ show?: boolean; label?: string }>(), { label: '加载中…' })
</script>
