<template>
  <span class="model-label">
    <ModelIcon :model="model" :provider="provider" :icon="icon" :upstream-models="upstreamModels" />
    <span class="model-label-text">{{ label || model || '—' }}</span>
  </span>
</template>
<script setup lang="ts">
import ModelIcon from './ModelIcon.vue'
defineProps<{ model?: string; label?: string; provider?: string; icon?: string; upstreamModels?: string[] }>()
</script>
