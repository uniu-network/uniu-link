<template>
  <div class="field">
    <span class="field-label">{{ label }}</span
    ><slot />
  </div>
</template>
<script setup lang="ts">
import { computed, provide } from 'vue'
import { fieldLabelKey } from '@/composables/useField'
const props = defineProps<{ label: string }>()
provide(
  fieldLabelKey,
  computed(() => props.label)
)
</script>
