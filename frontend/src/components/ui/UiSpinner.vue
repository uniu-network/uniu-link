<template>
  <div v-if="show" class="flex min-h-32 flex-col items-center justify-center gap-3 text-sm text-muted-foreground">
    <span class="h-6 w-6 animate-spin rounded-full border-2 border-foreground/30 border-t-foreground" />
    <span>{{ label }}</span>
  </div>
  <slot v-else />
</template>

<script setup lang="ts">
withDefaults(defineProps<{ show?: boolean; label?: string }>(), { label: '加载中...' })
</script>
