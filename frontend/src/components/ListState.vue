<template>
  <div v-if="error" class="empty-state" role="alert">
    <NavIcon name="error" class="message-symbol-error" />
    <p>{{ error }}</p>
    <UiButton @click="$emit('retry')">重试</UiButton>
  </div>
</template>
<script setup lang="ts">
import NavIcon from './NavIcon.vue'
import UiButton from './ui/UiButton.vue'
defineProps<{ error: string }>()
defineEmits<{ retry: [] }>()
</script>
