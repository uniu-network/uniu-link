<template>
  <fluent-text-area
    v-bind="$attrs"
    :value.prop="modelValue ?? ''"
    :aria-label="$attrs['aria-label'] || label || $attrs.placeholder"
    :disabled="disabled || formBusy"
    resize="vertical"
    @input="emit('update:modelValue', ($event.target as HTMLTextAreaElement).value)"
  />
</template>
<script setup lang="ts">
import { computed, inject } from 'vue'
import { fieldLabelKey, formBusyKey } from '@/composables/useField'
defineOptions({ inheritAttrs: false })
defineProps<{ modelValue?: string | null; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: string] }>()
const label = inject(
  fieldLabelKey,
  computed(() => '')
)
const formBusy = inject(
  formBusyKey,
  computed(() => false)
)
</script>
