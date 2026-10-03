<template>
  <header class="page-header">
    <div>
      <h1>{{ title }}</h1>
      <p v-if="description" class="page-description">{{ description }}</p>
    </div>
    <div v-if="$slots.default" class="actions"><slot /></div>
  </header>
</template>
<script setup lang="ts">
defineProps<{ title: string; description?: string }>()
</script>
