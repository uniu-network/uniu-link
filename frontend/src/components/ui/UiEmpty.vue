<template>
  <div class="flex min-h-32 flex-col items-center justify-center rounded-lg border border-dashed border-border bg-muted/30 p-8 text-center text-sm text-muted-foreground">
    <slot name="icon" />
    <p class="font-medium text-foreground">{{ title }}</p>
    <p v-if="description" class="mt-1">{{ description }}</p>
    <div v-if="$slots.default" class="mt-4"><slot /></div>
  </div>
</template>

<script setup lang="ts">
withDefaults(defineProps<{ title?: string; description?: string }>(), { title: '暂无数据' })
</script>
