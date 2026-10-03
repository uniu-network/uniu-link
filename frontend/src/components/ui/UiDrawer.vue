<template>
  <UiModal v-bind="$props" @update:open="$emit('update:open', $event)" @save="$emit('save')"
    ><slot /><template v-if="$slots.footer" #footer><slot name="footer" /></template
  ></UiModal>
</template>
<script setup lang="ts">
import UiModal from './UiModal.vue'
defineProps<{
  open: boolean
  title?: string
  width?: string
  busy?: boolean
  beforeClose?: () => Promise<boolean>
}>()
defineEmits<{ 'update:open': [value: boolean]; save: [] }>()
</script>
