<template>
  <div class="empty-state">
    <slot name="icon" />
    <p>{{ title }}</p>
    <p v-if="description" class="secondary-text">{{ description }}</p>
    <div v-if="$slots.default"><slot /></div>
  </div>
</template>
<script setup lang="ts">
withDefaults(defineProps<{ title?: string; description?: string }>(), { title: '暂无数据' })
</script>
